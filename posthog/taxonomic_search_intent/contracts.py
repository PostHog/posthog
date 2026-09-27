from django.db import models

from posthog.dataclasses import frozen


class SearchIntentSource(models.TextChoices):
    RULE = "rule", "Matched a value pattern"
    MODEL = "model", "Asked the decision model"
    SKIPPED = "skipped", "Not classified"


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
