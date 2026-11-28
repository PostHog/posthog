# Test cases for no-new-instance-settings.
# ruff: noqa
from django.conf import settings

from posthog.settings import dynamic_settings

CONSTANCE_CONFIG = {
    # ruleid: no-new-instance-settings
    "SOME_KILL_SWITCH": (False, "Turns the thing off.", bool),
    # ruleid: no-new-instance-settings
    "SOME_SIGNING_SECRET": ("", "Signs the thing.", str),
}

CONSTANCE_CONFIG: dict = {
    # ruleid: no-new-instance-settings
    "ANNOTATED_SETTING": (1, "An annotated config dict.", int),
}

# ruleid: no-new-instance-settings
CONSTANCE_CONFIG["ADDED_LATER"] = (1, "Added after the dict literal.", int)

# ruleid: no-new-instance-settings
CONSTANCE_CONFIG.update({"MERGED_IN": (1, "Merged into the dict.", int)})

# ruleid: no-new-instance-settings
CONSTANCE_CONFIG.setdefault("DEFAULTED_IN", (1, "Set as a default.", int))

# ruleid: no-new-instance-settings
CONSTANCE_CONFIG |= {"OR_MERGED": (1, "Merged with the |= operator.", int)}

# ruleid: no-new-instance-settings
settings.CONSTANCE_CONFIG["THROUGH_SETTINGS"] = (1, "Added through django settings.", int)

# ruleid: no-new-instance-settings
dynamic_settings.CONSTANCE_CONFIG.update({"THROUGH_MODULE": (1, "Added through the module.", int)})

# ok: no-new-instance-settings
default = CONSTANCE_CONFIG["SOME_KILL_SWITCH"][0]

# ok: no-new-instance-settings
keys = [key for key in CONSTANCE_CONFIG]

# ok: no-new-instance-settings
OTHER_CONFIG = {"NOT_AN_INSTANCE_SETTING": (1, "Some other dict.", int)}
