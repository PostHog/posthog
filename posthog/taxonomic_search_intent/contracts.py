from django.db import models

from posthog.dataclasses import frozen


class SearchIntentSource(models.TextChoices):
    RULE = "rule", "Matched a value pattern"
    MODEL = "model", "Asked the decision model"
    SKIPPED = "skipped", "Not classified"


class EventMatchOutcome(models.TextChoices):
    WRONG_LENGTH = "wrong_length", "The search is too short or too long to ask about"
    ONLY_VALUES = "only_values", "Nothing but values is left for the model to read"
    UNAVAILABLE = "unavailable", "The model could not answer at all"
    PARTIAL = "partial", "Some model requests failed, so an event it never asked about might have matched"
    NOTHING_LIKELY = "nothing_likely", "The model found no core event likely"
    NOT_INGESTED = "not_ingested", "The project never sent the likely events"
    MATCHED = "matched", "At least one likely event has data"


@frozen
class SearchIntentRequest:
    """What a person typed into the filter picker, and the tabs the picker shows them."""

    team_id: int
    query: str
    active_group_type: str
    available_group_types: tuple[str, ...]
    scene: str | None = None


@frozen
class SearchIntent:
    """The picker tab the search most likely belongs to. ``group_type`` is None when nothing was classified."""

    group_type: str | None
    confidence: float
    is_confident: bool
    source: SearchIntentSource
    suggests_switch: bool = False
    # The managed prompt version the model read, or None for a rule match, a skip or the bundled prompt.
    prompt_version: int | None = None
    # The search as the model read it, with values replaced by placeholders. None when the model did not answer.
    model_query: str | None = None


@frozen
class EventMatchRequest:
    """A search in the picker's events list that found nothing, to match against the PostHog core events."""

    team_id: int
    project_id: int
    query: str


@frozen
class EventMatch:
    """A core event the search may mean. ``probability`` is the model's confidence that the search names it."""

    name: str
    label: str
    probability: float


@frozen
class EventMatchAnswer:
    """The suggestions for a search, and the step that decided them, so an empty answer says why it is empty."""

    matches: list[EventMatch]
    outcome: EventMatchOutcome
