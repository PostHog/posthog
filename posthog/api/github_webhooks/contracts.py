from collections.abc import Mapping
from dataclasses import field

from posthog.dataclasses import frozen

type AnalyticsProperty = str | int | float | bool | None | list[AnalyticsProperty] | dict[str, AnalyticsProperty]


@frozen
class PullRequestAttribution:
    source: str
    team_id: int
    distinct_id: str
    groups: Mapping[str, str]
    properties: Mapping[str, AnalyticsProperty] = field(default_factory=dict)
    include_content: bool = False
    send_feature_flags: bool = False
