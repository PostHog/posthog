# Test cases for new-models-use-uuid7.
# ruff: noqa

from posthog.models.utils import UUIDModel, UUIDTModel


# ruleid: new-models-use-uuid7
class HogFlowOptimization(UUIDTModel):
    pass


# ruleid: new-models-use-uuid7
class WorkflowProposal(TeamScopedRootMixin, UUIDTModel):
    pass


# ruleid: new-models-use-uuid7
class TaggedItem(ModelActivityMixin, UUIDTModel, RootTeamMixin):
    pass


# ok: new-models-use-uuid7
class Suggestion(UUIDModel):
    pass


# ok: new-models-use-uuid7
class ScopedSuggestion(TeamScopedRootMixin, UUIDModel):
    pass
