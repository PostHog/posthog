# Overridden in posthog-cloud

import sys

from posthog.settings.utils import get_from_env, print_warning, str_to_bool

# Early exit to avoid issues with cloud not being properly included
if get_from_env("MULTI_TENANCY", False, type_cast=str_to_bool):
    print_warning(("️Environment variable MULTI_TENANCY is set, but cloud settings have not been included",))
    sys.exit("[ERROR] Stopping Django server…\n")
