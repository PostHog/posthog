from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

MAX_SOURCE_LENGTH = 100_000


class ParserRecipe(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """A team's net-new custom recipe for the message normalizer.

    Content-only storage. Custom recipes run before the builtin catch-all in the
    trace view; the frontend owns the merge against its bundled defaults.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    source = models.TextField()

    def __str__(self) -> str:
        return self.name
