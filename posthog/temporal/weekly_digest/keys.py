from enum import StrEnum
from uuid import UUID


class TeamDataKey(StrEnum):
    DASHBOARDS = "dashboards"
    EVENT_DEFINITIONS = "event-definitions"
    EXPERIMENTS_LAUNCHED = "experiments-launched"
    EXPERIMENTS_COMPLETED = "experiments-completed"
    EXTERNAL_DATA_SOURCES = "external-data-sources"
    FEATURE_FLAGS = "feature-flags"
    SAVED_FILTERS = "saved-filters"
    EXPIRING_RECORDINGS = "expiring-recordings"
    SURVEYS_LAUNCHED = "surveys-launched"


class UserDataKey(StrEnum):
    NOTIFY_TEAMS = "user-notify"
    PRODUCT_SUGGESTION = "product-suggestion"


def team_data_key(digest_key: str, kind: TeamDataKey, team_id: int) -> str:
    return f"{digest_key}-{kind}-{team_id}"


def org_digest_key(digest_key: str, org_id: UUID) -> str:
    return f"{digest_key}-{org_id}"


def user_data_key(digest_key: str, kind: UserDataKey, user_id: int) -> str:
    return f"{digest_key}-{kind}-{user_id}"
