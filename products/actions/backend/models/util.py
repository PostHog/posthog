from collections import (
    Counter,
    Counter as TCounter,
)

from posthog.models.property import PropertyIdentifier
from posthog.models.property.parse import parse_property_group_data

from products.actions.backend.models.action import Action


def get_action_tables_and_properties(action: Action) -> TCounter[PropertyIdentifier]:
    from posthog.models.property.util import extract_tables_and_properties

    result: TCounter[PropertyIdentifier] = Counter()

    for action_step in action.steps:
        if action_step.url:
            result[("$current_url", "event", None)] += 1
        result += extract_tables_and_properties(
            parse_property_group_data(action_step.properties or []).flat,
            team_id=action.team_id,
        )

    return result
