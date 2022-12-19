# Overridden in posthog-cloud

import sys

import structlog

from posthog.settings.utils import get_from_env, str_to_bool

logger = structlog.get_logger(__name__)

# TODO BW: Before we can remove posthog-cloud we need to remove this file

# Early exit to avoid issues with cloud not being properly included
if get_from_env("MULTI_TENANCY", False, type_cast=str_to_bool):
    logger.critical(("️Environment variable MULTI_TENANCY is set, but cloud settings have not been included",))
    sys.exit("[ERROR] Stopping Django server…\n")
