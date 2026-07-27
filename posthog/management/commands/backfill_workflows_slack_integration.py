import copy
import time
import logging
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = logging.getLogger(__name__)


# One-off backfill for team 2: the Slack integration was re-installed under a new
# primary key (173069). 40 hogflows still reference the old integration row (54567),
# which no longer exists, so their Slack steps fail at runtime. The UI auto-substitutes
# on render but never writes the new id back to the stored config until the user saves.
# Hard-coded by intent — this is not a generic remapper, just the one swap we need.
TEAM_ID = 2
OLD_INTEGRATION_ID = 54567
NEW_INTEGRATION_ID = 173069


def _rewrite_slack_workspace_in_actions(actions: Any) -> tuple[Any, list[str]]:
    """Return (new_actions, changed_action_ids). actions is left untouched if no match.

    Looks for `config.inputs.slack_workspace.value == OLD_INTEGRATION_ID` on any action
    and rewrites it to NEW_INTEGRATION_ID. The integration id is stored as a literal
    integer (no bytecode), so only the `value` needs swapping.
    """
    if not isinstance(actions, list):
        return actions, []

    changed_ids: list[str] = []
    new_actions = copy.deepcopy(actions)

    for action in new_actions:
        if not isinstance(action, dict):
            continue
        inputs = (action.get("config") or {}).get("inputs") or {}
        slack_workspace = inputs.get("slack_workspace")
        if not isinstance(slack_workspace, dict):
            continue
        if slack_workspace.get("value") == OLD_INTEGRATION_ID:
            slack_workspace["value"] = NEW_INTEGRATION_ID
            changed_ids.append(str(action.get("id") or "<unknown>"))

    return new_actions, changed_ids


class Command(BaseCommand):
    help = (
        f"One-off: rewrite stale Slack integration {OLD_INTEGRATION_ID} → {NEW_INTEGRATION_ID} "
        f"in HogFlow actions on team {TEAM_ID}."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run without making any changes to the database",
        )

    def handle(self, *args, **options):
        start_time = time.time()
        dry_run: bool = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("Running in DRY RUN mode — no changes will be made"))

        self.stdout.write(
            f"Scanning HogFlows for team {TEAM_ID}, "
            f"swapping slack_workspace {OLD_INTEGRATION_ID} → {NEW_INTEGRATION_ID}..."
        )

        # Team 2 has on the order of a few hundred hogflows. Pull them all in one go;
        # no pagination required at this scale, and a single transaction keeps the
        # write atomic for the team.
        flows = list(HogFlow.objects.filter(team_id=TEAM_ID).order_by("id"))
        total_count = len(flows)
        self.stdout.write(f"Found {total_count} HogFlows on team {TEAM_ID}")

        if total_count == 0:
            return

        updated_flows: list[HogFlow] = []
        per_flow_changes: list[tuple[str, list[str], list[str]]] = []
        error_count = 0

        for flow in flows:
            try:
                new_actions, actions_changed = _rewrite_slack_workspace_in_actions(flow.actions)
                draft_actions_changed: list[str] = []
                new_draft = flow.draft
                if isinstance(flow.draft, dict) and "actions" in flow.draft:
                    rewritten_draft_actions, draft_actions_changed = _rewrite_slack_workspace_in_actions(
                        flow.draft.get("actions")
                    )
                    if draft_actions_changed:
                        new_draft = {**flow.draft, "actions": rewritten_draft_actions}

                if not actions_changed and not draft_actions_changed:
                    continue

                flow.actions = new_actions
                flow.draft = new_draft
                updated_flows.append(flow)
                per_flow_changes.append((str(flow.id), actions_changed, draft_actions_changed))
            except Exception as e:
                error_count += 1
                logger.exception(
                    "Error processing HogFlow id=%s team_id=%s: %s",
                    flow.id,
                    flow.team_id,
                    e,
                )

        # Report planned changes before writing.
        for flow_id, actions_changed, draft_actions_changed in per_flow_changes:
            self.stdout.write(
                f"  {flow_id}: actions={actions_changed or '[]'} draft.actions={draft_actions_changed or '[]'}"
            )

        if updated_flows and not dry_run:
            # bulk_update skips post_save, which means worker reloads won't happen
            # automatically. That's fine for a one-off backfill — workers refresh their
            # caches on their own ticking interval, and we'd rather not spam reload
            # signals for every flow we touch.
            with transaction.atomic():
                HogFlow.objects.bulk_update(updated_flows, ["actions", "draft"], batch_size=200)

        duration = time.time() - start_time
        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone in {duration:.2f}s.\n"
                f"Scanned: {total_count}\n"
                f"{verb}: {len(updated_flows)}\n"
                f"Errors: {error_count}"
            )
        )

        if error_count > 0:
            self.stdout.write(self.style.WARNING(f"Check logs for details on {error_count} errors"))
