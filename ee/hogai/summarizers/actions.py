from collections import defaultdict

from posthog.models.action.action import Action, ActionStepJSON, ActionStepMatching
from posthog.schema import (
    PropertyOperator,
)

from .property_filters import (
    PropertyFilterCollectionDescriber,
    PropertyFilterTaxonomyEntry,
    retrieve_hardcoded_taxonomy,
)

PROPERTY_FILTER_VERBOSE_NAME: dict[PropertyOperator, str] = {
    PropertyOperator.EXACT: "matches exactly",
    PropertyOperator.IS_NOT: "is not",
    PropertyOperator.ICONTAINS: "contains",
    PropertyOperator.NOT_ICONTAINS: "doesn't contain",
    PropertyOperator.REGEX: "matches regex",
    PropertyOperator.NOT_REGEX: "doesn't match regex",
    PropertyOperator.GT: "greater than",
    PropertyOperator.GTE: "greater than or equal to",
    PropertyOperator.LT: "less than",
    PropertyOperator.LTE: "less than or equal to",
    PropertyOperator.IS_SET: "is set",
    PropertyOperator.IS_NOT_SET: "is not set",
    PropertyOperator.IS_DATE_EXACT: "is on exact date",
    PropertyOperator.IS_DATE_BEFORE: "is before date",
    PropertyOperator.IS_DATE_AFTER: "is after date",
    PropertyOperator.BETWEEN: "is between",
    PropertyOperator.NOT_BETWEEN: "is not between",
    PropertyOperator.MIN: "is min",
    PropertyOperator.MAX: "is max",
    PropertyOperator.IN_: "is in",
    PropertyOperator.NOT_IN: "is not in",
    PropertyOperator.IS_CLEANED_PATH_EXACT: "is cleaned path exact",
}


ACTION_MATCH_FILTER_VERBOSE_NAME: dict[ActionStepMatching, str] = {
    "regex": "matches regex",
    "exact": "matches exactly",
    "contains": "contains",
}


class ActionSummarizer:
    _action: Action
    _taxonomy: set[PropertyFilterTaxonomyEntry]
    _step_descriptions: list[str]

    def __init__(self, action: Action):
        self._action = action
        self._taxonomy = set()
        self._step_descriptions = []

        for index, step in enumerate(self._action.steps):
            step_desc, used_events = self._describe_action_step(step, index)
            self._step_descriptions.append(step_desc)
            self._taxonomy.update(used_events)

    @property
    def summary(self) -> str:
        steps = "\n\nOR\n\n".join(self._step_descriptions)
        description = f"Name: {self._action.name}\nDescription: {self._action.description or '-'}\n\n{steps}"
        return description

    @property
    def taxonomy_description(self) -> str:
        groups: dict[str, list[PropertyFilterTaxonomyEntry]] = defaultdict(list)
        for taxonomy in self._taxonomy:
            groups[taxonomy.group_verbose_name].append(taxonomy)

        group_descriptions = []
        for group, taxonomies in groups.items():
            description = f"Description of {group} for your reference:\n"
            description += "\n".join([f"- `{taxonomy.key}`: {taxonomy.description}" for taxonomy in taxonomies])
            group_descriptions.append(description)

        description = "\n\n".join(group_descriptions)
        return description

    def _describe_action_step(self, step: ActionStepJSON, index: int) -> tuple[str, set[PropertyFilterTaxonomyEntry]]:
        taxonomy: set[PropertyFilterTaxonomyEntry] = set()
        description: list[str] = []

        if step.event:
            description.append(f"event is `{step.event}`")
            if event_description := retrieve_hardcoded_taxonomy("events", step.event):
                taxonomy.add(PropertyFilterTaxonomyEntry(group="events", key=step.event, description=event_description))
        if step.text_matching and step.text:
            text_desc = f"element text {ACTION_MATCH_FILTER_VERBOSE_NAME[step.text_matching]} `{step.text}`"
            description.append(text_desc)
        if step.href_matching and step.href:
            href_desc = f"element `href` attribute {ACTION_MATCH_FILTER_VERBOSE_NAME[step.href_matching]} `{step.href}`"
            description.append(href_desc)
        if step.url_matching and step.url:
            url_desc = f"the URL of event {ACTION_MATCH_FILTER_VERBOSE_NAME[step.url_matching]} `{step.url}`"
            description.append(url_desc)
        if step.selector:
            html_desc = f"element matches HTML selector `{step.selector}`"
            description.append(html_desc)
        if step.tag_name:
            tag_desc = f"element tag is `{step.tag_name}`"
            description.append(tag_desc)

        if step.properties:
            property_desc, used_properties = PropertyFilterCollectionDescriber(filters=step.properties).describe()
            description.append(property_desc)
            taxonomy.update(used_properties)

        conditions = " AND ".join(description)
        return f"Match group {index + 1}: {conditions}", taxonomy
