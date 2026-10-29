from collections import defaultdict
from collections.abc import Iterator

from django.db.models import CharField
from django.db.models.functions import Cast

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.sharing_configuration import SharingConfiguration


@frozen
class SharingAttributionBatch:
    kind: str
    scanned: int
    updated: int


class SharingAttributionBackfill:
    resource_scopes = {
        "dashboard": ("Dashboard", "id"),
        "insight": ("Insight", "id"),
        "notebook": ("Notebook", "short_id"),
        "recording": ("SessionRecording", "session_id"),
    }

    def run(self, *, batch_size: int, team_id: int | None, dry_run: bool) -> Iterator[SharingAttributionBatch]:
        for kind, (scope, identifier) in self.resource_scopes.items():
            pending = SharingConfiguration.objects.filter(shared_by__isnull=True, **{f"{kind}__isnull": False})
            if team_id is not None:
                pending = pending.filter(team_id=team_id)
            last_id = 0
            while True:
                batch = list(
                    pending.filter(pk__gt=last_id)
                    .annotate(log_id=Cast(f"{kind}__{identifier}", output_field=CharField()))
                    .order_by("pk")
                    .values_list("pk", "team_id", "log_id")[:batch_size]
                )
                if not batch:
                    break
                last_id = batch[-1][0]
                latest_publishers = {
                    (log_team_id, item_id): user_id
                    for log_team_id, item_id, user_id in ActivityLog.objects.filter(
                        team_id__in={row[1] for row in batch},
                        item_id__in={row[2] for row in batch},
                        scope=scope,
                        activity="sharing enabled",
                    )
                    .order_by("team_id", "item_id", "-created_at", "-id")
                    .distinct("team_id", "item_id")
                    .values_list("team_id", "item_id", "user_id")
                }
                by_publisher: dict[int, list[int]] = defaultdict(list)
                for configuration_id, configuration_team_id, log_id in batch:
                    publisher = latest_publishers.get((configuration_team_id, log_id))
                    if publisher is not None:
                        by_publisher[publisher].append(configuration_id)
                updated = 0
                for publisher, ids in by_publisher.items():
                    if dry_run:
                        updated += len(ids)
                    else:
                        # Keep attribution written by a concurrent sharing request.
                        updated += SharingConfiguration.objects.filter(pk__in=ids, shared_by__isnull=True).update(
                            shared_by_id=publisher
                        )
                yield SharingAttributionBatch(kind=kind, scanned=len(batch), updated=updated)
