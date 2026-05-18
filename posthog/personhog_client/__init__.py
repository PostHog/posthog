from typing import Literal

from posthog.personhog_client.proto import CONSISTENCY_LEVEL_EVENTUAL, CONSISTENCY_LEVEL_STRONG, ReadOptions

ReadConsistency = Literal["strong", "eventual"]


def consistency_to_read_options(consistency: ReadConsistency) -> ReadOptions:
    level = CONSISTENCY_LEVEL_STRONG if consistency == "strong" else CONSISTENCY_LEVEL_EVENTUAL
    return ReadOptions(consistency=level)
