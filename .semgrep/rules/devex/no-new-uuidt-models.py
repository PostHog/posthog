# Test cases for no-new-uuidt-models.
# ruff: noqa
from posthog.models.utils import UUIDModel, UUIDTModel


# ruleid: no-new-uuidt-models
class LegacyKey(UUIDTModel):
    pass


# ruleid: no-new-uuidt-models
class LegacyKeyWithMixin(TeamScopedRootMixin, UUIDTModel):
    pass


# ok: no-new-uuidt-models
class CurrentKey(UUIDModel):
    pass
