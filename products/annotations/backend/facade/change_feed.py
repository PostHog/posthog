"""Change feed contract types: what the change feed returns to its API, MCP tools and other products."""

from datetime import datetime

from pydantic.dataclasses import dataclass

from posthog.enums import LabeledStrEnum


class ChangeKind(LabeledStrEnum):
    FEATURE_FLAG = "feature_flag", "Feature flag"
    EXPERIMENT = "experiment", "Experiment"
    RELEASE = "release", "Release"
    ANNOTATION = "annotation", "Annotation"


@dataclass(frozen=True)
class ChangeWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("start must not be after end")


@dataclass(frozen=True)
class KindVisibility:
    # When set, the user may see only these object ids. Otherwise they may see all except blocked_ids.
    allowed_ids: frozenset[str] | None = None
    blocked_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    timestamp: datetime
    item_id: str
    name: str | None
    activity: str
    changed_fields: list[str]
    service: str | None
    actor_name: str | None


@dataclass(frozen=True)
class ChangeFeed:
    results: list[Change]
    has_more: bool
