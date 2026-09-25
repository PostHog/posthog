import time
from copy import deepcopy
from typing import Any

from django.core.management.base import BaseCommand
from django.core.paginator import Paginator
from django.db import transaction
from django.test import RequestFactory

import structlog

from products.workflows.backend.api.hog_flow import (
    HogFlowSerializer,
    TemplateCache,
    mask_secret_action_inputs,
    merge_secret_maps,
    partition_flow_secrets,
    plaintext_secret_map,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = structlog.get_logger(__name__)


def _secret_values(secrets: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    # Compare secrets by value only. The save recompiles each input, so its bytecode can change.
    return {
        action_id: {key: value.get("value") if isinstance(value, dict) else value for key, value in inputs.items()}
        for action_id, inputs in secrets.items()
        if inputs
    }


class Command(BaseCommand):
    help = "Refresh HogFlows (all statuses) by re-saving them to trigger reload on workers"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id", type=int, help="Team ID to refresh HogFlows for (if not provided, processes all teams)"
        )
        parser.add_argument(
            "--hog-flow-id",
            type=str,
            help="Specific HogFlow ID to refresh (if provided, only this flow is processed)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be re-saved, and which flows no longer validate, without saving.",
        )
        parser.add_argument(
            "--page-size",
            type=int,
            default=1000,
            help="Number of flows to process per page (default: 1000)",
        )

    def handle(self, *args, **options):
        start_time = time.time()
        total_processed = 0
        total_updated = 0
        error_count = 0

        team_id = options.get("team_id")
        hog_flow_id = options.get("hog_flow_id")
        page_size = options.get("page_size", 1000)
        dry_run: bool = options.get("dry_run", False)

        self.stdout.write("Starting HogFlow refresh..." + (" (dry run, nothing is saved)" if dry_run else ""))

        queryset = HogFlow.objects.all()

        if hog_flow_id:
            queryset = queryset.filter(id=hog_flow_id)
            self.stdout.write(f"Processing single HogFlow: {hog_flow_id}")
        elif team_id:
            queryset = queryset.filter(team_id=team_id)
            self.stdout.write(f"Processing HogFlows for team: {team_id}")
        else:
            self.stdout.write("Processing HogFlows for all teams")

        total_count = queryset.count()
        self.stdout.write(f"Found {total_count} HogFlows to process")

        if total_count == 0:
            self.stdout.write(self.style.WARNING("No HogFlows found matching criteria"))
            return

        paginator = Paginator(queryset.order_by("id").values_list("id", flat=True), page_size)

        for page_num in paginator.page_range:
            page = paginator.page(page_num)

            self.stdout.write(f"Processing page {page_num}/{paginator.num_pages} ({len(page.object_list)} flows)...")

            for flow_id in page.object_list:
                hog_flow = None
                try:
                    # Reload and lock each flow just before its save. A copy loaded with the page goes
                    # stale, and a full save of it overwrites any edit made while the page runs.
                    with transaction.atomic():
                        flows = HogFlow.objects if dry_run else HogFlow.objects.select_for_update()
                        hog_flow = flows.filter(id=flow_id).first()
                        if hog_flow is None:
                            continue
                        total_processed += 1

                        # Create a mock request context for the serializer
                        request = RequestFactory().post("/")
                        if hog_flow.created_by:
                            request.user = hog_flow.created_by

                        def get_team_func(flow=hog_flow):
                            return flow.team

                        serializer_context = {
                            "request": request,
                            "team_id": hog_flow.team_id,
                            "get_team": get_team_func,
                        }

                        # Stored actions hold no secret inputs. Resend each live secret as the
                        # {"secret": true} marker, so validation recovers it as it does for an editor save.
                        template_cache: TemplateCache = {}
                        live_secrets = merge_secret_maps(
                            plaintext_secret_map(hog_flow.actions, template_cache), hog_flow.encrypted_inputs
                        )
                        actions = mask_secret_action_inputs(
                            deepcopy(hog_flow.actions or []), live_secrets, template_cache
                        )

                        # Get the current data from the HogFlow
                        data = {
                            "name": hog_flow.name,
                            "description": hog_flow.description,
                            "status": hog_flow.status,
                            "trigger": hog_flow.trigger,
                            "trigger_masking": hog_flow.trigger_masking,
                            "conversion": hog_flow.conversion,
                            "exit_condition": hog_flow.exit_condition,
                            "edges": hog_flow.edges,
                            "actions": actions,
                            "variables": hog_flow.variables,
                        }

                        # Process through serializer to regenerate bytecode
                        serializer = HogFlowSerializer(
                            instance=hog_flow, data=data, context=serializer_context, partial=True
                        )

                        # Validation recovers secrets with the draft first, because an editor saw the
                        # draft. A refresh writes the live store, so it must recover the live secrets.
                        draft_secrets = hog_flow.draft_encrypted_inputs
                        hog_flow.draft_encrypted_inputs = None
                        try:
                            is_valid = serializer.is_valid()
                        finally:
                            hog_flow.draft_encrypted_inputs = draft_secrets

                        if is_valid:
                            _, written_secrets = partition_flow_secrets(
                                serializer.validated_data.get("actions") or [], template_cache
                            )
                            if _secret_values(written_secrets) != _secret_values(live_secrets):
                                # A save that changes a secret can delete a credential that nobody can
                                # enter again. Skip the workflow and name it.
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"Secrets would change: team {hog_flow.team_id}, workflow {hog_flow.id} ({hog_flow.name!r})"
                                    )
                                )
                                raise Exception("Refresh would change the stored secrets")
                            if not dry_run:
                                serializer.save()
                            total_updated += 1
                            logger.info(
                                "Would refresh HogFlow" if dry_run else "Successfully refreshed HogFlow",
                                hog_flow_id=str(hog_flow.id),
                                team_id=hog_flow.team_id,
                                status=hog_flow.status,
                                name=hog_flow.name,
                                version=hog_flow.version,
                                dry_run=dry_run,
                            )
                        else:
                            # A workflow that no longer validates cannot be re-saved, so it keeps whatever
                            # it was last compiled against. Name it: the owner has to fix it or turn it off.
                            self.stdout.write(
                                self.style.WARNING(
                                    f"Does not validate: team {hog_flow.team_id}, workflow {hog_flow.id} ({hog_flow.name!r})"
                                )
                            )
                            raise Exception(f"Serializer validation failed: {serializer.errors}")

                except Exception as e:
                    error_count += 1
                    logger.error(
                        "Error refreshing HogFlow",
                        hog_flow_id=str(flow_id),
                        team_id=hog_flow.team_id if hog_flow else None,
                        status=hog_flow.status if hog_flow else None,
                        name=hog_flow.name if hog_flow else None,
                        error=str(e),
                        exc_info=True,
                    )
                    self.stdout.write(self.style.ERROR(f"Error processing flow {flow_id}: {str(e)}"))

        # Output summary
        duration = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'Dry run' if dry_run else 'Refresh'} completed in {duration:.2f}s.\n"
                f"Processed: {total_processed}\n"
                f"{'Would update' if dry_run else 'Updated'}: {total_updated}\n"
                f"Errors: {error_count}"
            )
        )

        if error_count > 0:
            self.stdout.write(self.style.WARNING(f"Check logs for details on {error_count} errors encountered"))
