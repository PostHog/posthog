from collections import defaultdict
from uuid import uuid4

from django.core.management.base import BaseCommand
from django.db import transaction

from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric


class Command(BaseCommand):
    help = "Fix ExperimentSavedMetric records that share the same query.uuid within a team"

    def handle(self, *args, **options):
        dry_run = False

        # 1. Find duplicate groups: (team_id, uuid) → [saved_metric_ids]
        uuid_to_metrics: dict[tuple[int, str], list[int]] = defaultdict(list)
        for sm_id, team_id, query in ExperimentSavedMetric.objects.filter(query__uuid__isnull=False).values_list(
            "id", "team_id", "query"
        ):
            uuid = query.get("uuid") if isinstance(query, dict) else None
            if uuid:
                uuid_to_metrics[(team_id, uuid)].append(sm_id)

        duplicates = {k: v for k, v in uuid_to_metrics.items() if len(v) > 1}

        if not duplicates:
            self.stdout.write(self.style.SUCCESS("No duplicate UUIDs found."))
            return

        total_groups = len(duplicates)
        total_to_fix = sum(len(ids) - 1 for ids in duplicates.values())
        self.stdout.write(f"Found {total_groups} duplicate groups, {total_to_fix} records to fix.\n")

        # 2. For each group, keep the first record's UUID and reassign the rest
        # Maps saved_metric_id → (old_uuid, new_uuid)
        uuid_replacements: dict[int, tuple[str, str]] = {}
        # Maps old_uuid → set of all saved_metric_ids in that duplicate group
        old_uuid_to_group: dict[str, set[int]] = {}

        for (team_id, old_uuid), metric_ids in sorted(duplicates.items()):
            keep_id = metric_ids[0]
            fix_ids = metric_ids[1:]
            old_uuid_to_group[old_uuid] = set(metric_ids)

            self.stdout.write(f"  team={team_id}  old query.uuid={old_uuid}")
            self.stdout.write(f"    keeping saved_metric id={keep_id}")

            for sm_id in fix_ids:
                new_uuid = str(uuid4())
                self.stdout.write(f"    fixing  saved_metric id={sm_id}  new query.uuid={new_uuid}")
                uuid_replacements[sm_id] = (old_uuid, new_uuid)

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run — no changes made."))
            return

        # 3. Apply changes in a transaction
        with transaction.atomic():
            # 3a. Update saved metric queries
            metrics_to_update: list[ExperimentSavedMetric] = []
            for sm in ExperimentSavedMetric.objects.filter(id__in=uuid_replacements.keys()):
                old_uuid, new_uuid = uuid_replacements[sm.id]
                query = dict(sm.query)
                query["uuid"] = new_uuid
                sm.query = query
                metrics_to_update.append(sm)

            ExperimentSavedMetric.objects.bulk_update(metrics_to_update, ["query"], batch_size=500)
            self.stdout.write(f"\nUpdated {len(metrics_to_update)} saved metric queries.")

            # 3b. Update experiment ordering arrays
            #
            # The ordering arrays currently have ONE entry of old_uuid X for what
            # may be multiple linked metrics. After the fix each metric has its own
            # UUID, so we need to expand that single entry.
            #
            # Strategy: for each affected experiment, find the position of old_uuid
            # in the ordering and splice in the current UUIDs of every linked metric
            # that belonged to that duplicate group.

            # Find all experiments linked to ANY metric in the duplicate groups
            all_group_metric_ids = set()
            for group_ids in old_uuid_to_group.values():
                all_group_metric_ids.update(group_ids)

            affected_links = list(
                ExperimentToSavedMetric.objects.filter(saved_metric_id__in=all_group_metric_ids).select_related(
                    "saved_metric"
                )
            )

            # Group links by experiment
            links_by_experiment: dict[int, list[ExperimentToSavedMetric]] = defaultdict(list)
            for link in affected_links:
                links_by_experiment[link.experiment_id].append(link)

            experiments_updated = 0
            for experiment_id, links in links_by_experiment.items():
                experiment = Experiment.objects.get(id=experiment_id)
                primary_ordering = list(experiment.primary_metrics_ordered_uuids or [])
                secondary_ordering = list(experiment.secondary_metrics_ordered_uuids or [])
                changed = False

                # Group this experiment's links by old_uuid
                links_by_old_uuid: dict[str, list[ExperimentToSavedMetric]] = defaultdict(list)
                for link in links:
                    sm_id = link.saved_metric_id
                    if sm_id in uuid_replacements:
                        old_uuid = uuid_replacements[sm_id][0]
                    else:
                        # This is the "kept" metric — find its old_uuid via the group map
                        current_uuid = link.saved_metric.query.get("uuid") if link.saved_metric.query else None
                        old_uuid = current_uuid  # kept metric retains the old UUID
                    if old_uuid:
                        links_by_old_uuid[old_uuid].append(link)

                for old_uuid, group_links in links_by_old_uuid.items():
                    # Collect the current UUIDs for each linked metric, split by role
                    primary_uuids: list[str] = []
                    secondary_uuids: list[str] = []
                    for link in group_links:
                        current_uuid = link.saved_metric.query.get("uuid") if link.saved_metric.query else None
                        if not current_uuid:
                            continue
                        role = (link.metadata or {}).get("type", "primary")
                        if role == "primary":
                            primary_uuids.append(current_uuid)
                        else:
                            secondary_uuids.append(current_uuid)

                    # Expand old_uuid in primary ordering
                    if old_uuid in primary_ordering:
                        idx = primary_ordering.index(old_uuid)
                        # Replace the single old_uuid with all primary UUIDs from this group
                        # (includes old_uuid itself if the kept metric is linked as primary)
                        primary_ordering[idx : idx + 1] = primary_uuids
                        changed = True
                    elif primary_uuids:
                        primary_ordering.extend(primary_uuids)
                        changed = True

                    # Expand old_uuid in secondary ordering
                    if old_uuid in secondary_ordering:
                        idx = secondary_ordering.index(old_uuid)
                        secondary_ordering[idx : idx + 1] = secondary_uuids
                        changed = True
                    elif secondary_uuids:
                        secondary_ordering.extend(secondary_uuids)
                        changed = True

                if changed:
                    experiment.primary_metrics_ordered_uuids = primary_ordering
                    experiment.secondary_metrics_ordered_uuids = secondary_ordering
                    experiment.save(update_fields=["primary_metrics_ordered_uuids", "secondary_metrics_ordered_uuids"])
                    experiments_updated += 1

            self.stdout.write(f"Updated {experiments_updated} experiment ordering arrays.")

        self.stdout.write(self.style.SUCCESS("\nDone."))
