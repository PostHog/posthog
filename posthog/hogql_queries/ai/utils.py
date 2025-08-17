from abc import ABC
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from posthog.caching.utils import ThresholdMode, is_stale
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.models.team.team import Team

try:
    from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
except ImportError:
    CORE_FILTER_DEFINITIONS_BY_GROUP = {}

if TYPE_CHECKING:
    from posthog.taxonomy.taxonomy import CoreFilterDefinition


class TaxonomyCacheMixin(ABC):
    team: Team

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        """
        Despite the lazy mode, it caches for an hour by default. We don't want frequent updates here.
        """
        return is_stale(self.team, date_to=None, interval=None, last_refresh=last_refresh, mode=ThresholdMode.AI)

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        return None


class TaxonomyFiltersMixin:
    def _is_taxonomy_definition_ignored(self, definition: "CoreFilterDefinition") -> bool:
        return definition.get("system") or definition.get("ignored_in_assistant")

    def _get_ignored_system_events(self) -> set[str]:
        """Static list of events that are ignored in the AI assistant."""
        return {
            event
            for event, event_core_definition in CORE_FILTER_DEFINITIONS_BY_GROUP.get("events", {}).items()
            if self._is_taxonomy_definition_ignored(event_core_definition)
        }

    def _get_ignored_system_events_expr(self) -> ast.Expr:
        """Expression to filter out system and ignored events in the AI assistant."""
        return parse_expr(
            "event NOT IN {events}",
            placeholders={
                "events": ast.Array(exprs=[ast.Constant(value=event) for event in self._get_ignored_system_events()])
            },
        )

    def _get_ignored_system_event_properties(self) -> set[str]:
        """Static list of properties that are ignored in the AI assistant."""
        return {
            prop
            for prop, prop_core_definition in CORE_FILTER_DEFINITIONS_BY_GROUP.get("event_properties", {}).items()
            if self._is_taxonomy_definition_ignored(prop_core_definition)
        }

    def _get_ignored_properties(self) -> set[str]:
        return {
            # events
            r"\$set",
            r"\$time",
            r"\$set_once",
            r"\$sent_at",
            "distinct_id",
            # privacy-related
            r"\$ip",
            # feature flags and experiments
            r"\$feature\/",
            # flatten-properties-plugin
            "__",
            # other metadata
            "phjs",
            "survey_dismissed",
            "survey_responded",
            "partial_filter_chosen",
            "changed_action",
            "window-id",
            "changed_event",
            "partial_filter",
        }

    def _get_ignored_properties_regex_expr(self) -> ast.Expr:
        """Excluded properties across all entity types that are reserved for internal use or deprecated like `$set`, `$time`, `$set_once`, `$feature/*`, the flattener plugin, etc."""
        regex_conditions = "|".join(self._get_ignored_properties())
        return ast.Constant(value=f"({regex_conditions})")
