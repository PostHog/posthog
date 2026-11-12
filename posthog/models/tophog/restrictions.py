from django.db import transaction

from posthog.models.event_ingestion_restriction_config import (
    EventIngestionRestrictionConfig,
    regenerate_redis_for_restriction_type,
)
from posthog.models.team.team import Team

# Maps tophog key fields to EventIngestionRestrictionConfig filter fields, used both for
# matching existing restrictions against a tophog entry and for prefilling the add form
RESTRICTION_FILTER_FIELDS = {
    "distinct_id": "distinct_ids",
    "session_id": "session_ids",
    "event_name": "event_names",
    "event_uuid": "event_uuids",
}

# Maps tophog pipeline names (INGESTION_PIPELINE deployment values) to
# EventIngestionRestrictionConfig pipeline values until the naming is unified
TOPHOG_TO_RESTRICTION_PIPELINE = {
    "analytics": "analytics",
    "sessionreplay": "session_recordings",
    "errortracking": "errortracking",
    "clientwarnings": "clientwarnings",
    "heatmaps": "heatmaps",
    "ai": "ai",
}


def resolve_team_tokens(keys: list[dict[str, str]]) -> dict[str, str]:
    """Map team_id (as it appears in tophog keys) to the team's API token."""
    team_ids = {key["team_id"] for key in keys if key.get("team_id", "").isdigit()}
    if not team_ids:
        return {}
    teams = Team.objects.filter(id__in=[int(team_id) for team_id in team_ids]).values_list("id", "api_token")
    return {str(team_id): api_token for team_id, api_token in teams}


def key_token(key: dict[str, str], tokens_by_team_id: dict[str, str]) -> str:
    token = key.get("token", "")
    if token and token != "unknown":
        return token
    return tokens_by_team_id.get(key.get("team_id", ""), "")


def map_pipelines(tophog_pipelines: list[str]) -> list[str]:
    return sorted({TOPHOG_TO_RESTRICTION_PIPELINE[p] for p in tophog_pipelines if p in TOPHOG_TO_RESTRICTION_PIPELINE})


def unmapped_pipelines(tophog_pipelines: list[str]) -> list[str]:
    return [p for p in tophog_pipelines if p not in TOPHOG_TO_RESTRICTION_PIPELINE]


def restrictions_for_token(token: str) -> list[EventIngestionRestrictionConfig]:
    return list(EventIngestionRestrictionConfig.objects.filter(token=token).order_by("restriction_type"))


def find_restriction(restriction_id: str, token: str) -> EventIngestionRestrictionConfig | None:
    return EventIngestionRestrictionConfig.objects.filter(pk=restriction_id, token=token).first()


def extendable_fields(restriction: EventIngestionRestrictionConfig, key: dict[str, str]) -> list[str]:
    """Filter fields whose configured values exclude the tophog entry's value.

    Only non-empty lists qualify: appending to an empty list would narrow a
    match-everything filter down to a single value instead of extending it.
    """
    extendable = []
    for key_field, config_field in RESTRICTION_FILTER_FIELDS.items():
        value = key.get(key_field)
        configured = getattr(restriction, config_field) or []
        if value and configured and value not in configured:
            extendable.append(config_field)
    return extendable


def restriction_matches(
    restriction: EventIngestionRestrictionConfig, key: dict[str, str], tophog_pipelines: list[str]
) -> bool:
    """Whether an existing restriction already covers the tophog entry described by key and pipelines.

    Mirrors the ingestion matching semantics: an empty filter list matches everything,
    a non-empty list matches if it contains the entry's value (fields combine with AND).
    Key fields absent from the tophog entry don't disqualify a restriction.

    Pipelines require full coverage: every one of the entry's pipelines must map to a
    restriction pipeline the restriction applies to. Unmapped pipelines can't be
    restricted at all, so an entry that includes one is never covered.
    """
    if extendable_fields(restriction, key):
        return False
    if tophog_pipelines:
        mapped = [TOPHOG_TO_RESTRICTION_PIPELINE.get(p) for p in tophog_pipelines]
        if None in mapped:
            return False
        if restriction.pipelines and not set(mapped) <= set(restriction.pipelines):
            return False
    return True


def extend_restriction(restriction: EventIngestionRestrictionConfig, key: dict[str, str]) -> list[str]:
    """Append the tophog entry's key values to the restriction's filter lists; returns changed fields."""
    # Lock the row, so two staff extending the same restriction at once both keep their values.
    with transaction.atomic():
        locked = EventIngestionRestrictionConfig.objects.select_for_update().get(pk=restriction.pk)
        changed = extendable_fields(locked, key)
        if not changed:
            return []
        values = {
            config_field: [*getattr(locked, config_field), key[key_field]]
            for key_field, config_field in RESTRICTION_FILTER_FIELDS.items()
            if config_field in changed
        }
        # update() skips the post_save rebuild, which would publish a snapshot before this commit and could
        # drop a concurrent change to another restriction of the same type.
        EventIngestionRestrictionConfig.objects.filter(pk=locked.pk).update(**values)
        restriction_type = locked.restriction_type
        transaction.on_commit(lambda: regenerate_redis_for_restriction_type(restriction_type))
    return changed
