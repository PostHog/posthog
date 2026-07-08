import json
from typing import TYPE_CHECKING

import posthoganalytics
from pydantic import ValidationError
from rest_framework import exceptions

from posthog.schema import PropertyFilterType, RecordingOrder, RecordingsQuery

if TYPE_CHECKING:
    from posthog.models import Team

SURFACING_SCORE_ORDER_FLAG = "replay-playlist-surfacing-score"
RELEVANCE_SORT_EXPERIMENT_FLAG = "replay-playlist-relevance-sort-experiment"


def recordings_query_has_event_filters(query: RecordingsQuery) -> bool:
    """Whether a query carries something the matching_events endpoint can highlight: an event filter,
    an action filter, or an event-property filter. The endpoint rejects queries without one, so both
    the endpoint's own precondition and any caller that decides whether to hit it share this check."""
    has_event_properties = any(
        getattr(prop, "type", None) == PropertyFilterType.EVENT for prop in (query.properties or [])
    )
    return bool(query.events) or bool(query.actions) or has_event_properties


def gate_surfacing_score_order(query: RecordingsQuery, team: "Team | None") -> None:
    """`surfacing_score` ordering is gated behind a feature flag. It's exposed to clients via the
    generated RecordingOrder enum (both the REST list endpoint and the MCP query), so the gate has to
    be enforced server-side, not just in the UI. The gate is evaluated against the team, not the
    requesting user, so a team's shared recordings list is deterministic across colleagues: two users
    with identical permissions must get the same ordering (and therefore the same paginated set of
    recordings). When neither the surfacing-score rollout nor the relevance-sort experiment's test arm
    is enabled for the team (or there's no team to evaluate against), fall back to the default ordering
    rather than erroring on an otherwise valid request."""
    if query.order != RecordingOrder.SURFACING_SCORE:
        return

    if team is None or not _can_order_by_surfacing_score(team):
        query.order = RecordingOrder.START_TIME


def _can_order_by_surfacing_score(team: "Team") -> bool:
    # Scope to the team so the flag/experiment arm is the same for everyone viewing this team's list.
    distinct_id = str(team.id)
    if posthoganalytics.feature_enabled(
        SURFACING_SCORE_ORDER_FLAG,
        distinct_id,
        send_feature_flag_events=False,
    ):
        return True
    # The relevance-sort experiment's test arm needs the same ordering capability, otherwise the server
    # resets its default sort back to recency and the experiment measures nothing.
    return (
        posthoganalytics.get_feature_flag(
            RELEVANCE_SORT_EXPERIMENT_FLAG,
            distinct_id,
            send_feature_flag_events=False,
        )
        == "test"
    )


def clean_prompt_whitespace(prompt: str) -> str:
    """
    Cleans unnecessary whitespace from prompts while preserving single spaces between words.
    Args:
        prompt: The input string to clean
    Returns:
        String with normalized whitespace - single spaces between words, no leading/trailing whitespace
    """
    # Replace multiple spaces with single space and strip leading/trailing whitespace
    return " ".join(prompt.split())


def query_as_params_to_dict(params_dict: dict) -> dict:
    """
    before (if ever) we convert this to a query runner that takes a post
    we need to convert to a valid dict from the data that arrived in query params
    """
    converted = {}
    for key in params_dict:
        try:
            converted[key] = json.loads(params_dict[key]) if isinstance(params_dict[key], str) else params_dict[key]
        except json.JSONDecodeError:
            converted[key] = params_dict[key]

    # we used to accept this value,
    # but very unlikely to receive it now
    # it's safe to pop
    # to make sure any old URLs or filters don't error
    # if they still include it
    converted.pop("as_query", None)

    return converted


def filter_from_params_to_query(params: dict) -> RecordingsQuery:
    data_dict = query_as_params_to_dict(params)
    # we used to send `version` and it's not part of query, so we pop to make sure
    data_dict.pop("version", None)
    # we used to send `hogql_filtering` and it's not part of query, so we pop to make sure
    data_dict.pop("hogql_filtering", None)

    try:
        return RecordingsQuery.model_validate(data_dict)
    except ValidationError as pydantic_validation_error:
        raise exceptions.ValidationError(json.dumps(pydantic_validation_error.errors()))
