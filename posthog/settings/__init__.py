"""
Django settings for posthog project.

Generated by 'django-admin startproject' using Django 2.2.5.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.2/ref/settings/
"""
# isort: skip_file

import os
from typing import Dict, List

# :TRICKY: Imported before anything else to support overloads
from posthog.settings.overrides import *

from posthog.settings.logs import *
from posthog.settings.base_variables import *

from posthog.settings.access import *
from posthog.settings.async_migrations import *
from posthog.settings.celery import *
from posthog.settings.data_stores import *
from posthog.settings.demo import *
from posthog.settings.dynamic_settings import *
from posthog.settings.ee import *
from posthog.settings.ingestion import *
from posthog.settings.feature_flags import *
from posthog.settings.geoip import *
from posthog.settings.metrics import *
from posthog.settings.schedules import *
from posthog.settings.sentry import *
from posthog.settings.shell_plus import *
from posthog.settings.service_requirements import *
from posthog.settings.object_storage import *
from posthog.settings.temporal import *
from posthog.settings.web import *
from posthog.settings.airbyte import *

from posthog.settings.utils import get_from_env, str_to_bool


# Instance configuration preferences
# https://posthog.com/docs/self-host/configure/environment-variables
debug_queries = get_from_env("DEBUG_QUERIES", False, type_cast=str_to_bool)
disable_paid_fs = get_from_env("DISABLE_PAID_FEATURE_SHOWCASING", False, type_cast=str_to_bool)
INSTANCE_PREFERENCES = {
    "debug_queries": debug_queries,
    "disable_paid_fs": disable_paid_fs,
}

SITE_URL: str = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")
INSTANCE_TAG: str = os.getenv("INSTANCE_TAG", "none")

if DEBUG:
    JS_URL = os.getenv("JS_URL", "http://localhost:8234").rstrip("/")
else:
    JS_URL = os.getenv("JS_URL", "").rstrip("/")

DISABLE_MMDB = get_from_env(
    "DISABLE_MMDB", TEST, type_cast=str_to_bool
)  # plugin server setting disabling GeoIP feature
PLUGINS_PREINSTALLED_URLS: List[str] = (
    os.getenv(
        "PLUGINS_PREINSTALLED_URLS",
        "https://www.npmjs.com/package/@posthog/geoip-plugin",
    ).split(",")
    if not DISABLE_MMDB
    else []
)
PLUGINS_RELOAD_PUBSUB_CHANNEL = os.getenv("PLUGINS_RELOAD_PUBSUB_CHANNEL", "reload-plugins")

# Tokens used when installing plugins, for example to get the latest commit SHA or to download private repositories.
# Used mainly to get around API limits and only if no ?private_token=TOKEN found in the plugin URL.
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", None)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)
NPM_TOKEN = os.getenv("NPM_TOKEN", None)


# Whether to capture time-to-see-data metrics
CAPTURE_TIME_TO_SEE_DATA = get_from_env("CAPTURE_TIME_TO_SEE_DATA", False, type_cast=str_to_bool)

# Whether kea should be act in verbose mode
KEA_VERBOSE_LOGGING = get_from_env("KEA_VERBOSE_LOGGING", False, type_cast=str_to_bool)

# Only written in specific scripts - do not use outside of them.
PERSON_ON_EVENTS_OVERRIDE = get_from_env("PERSON_ON_EVENTS_OVERRIDE", optional=True, type_cast=str_to_bool)

# Only written in specific scripts - do not use outside of them.
PERSON_ON_EVENTS_V2_OVERRIDE = get_from_env("PERSON_ON_EVENTS_V2_OVERRIDE", optional=True, type_cast=str_to_bool)

# Wether to use insight queries converted to HogQL.
HOGQL_INSIGHTS_OVERRIDE = get_from_env("HOGQL_INSIGHTS_OVERRIDE", optional=True, type_cast=str_to_bool)

HOOK_EVENTS: Dict[str, str] = {}

# Support creating multiple organizations in a single instance. Requires a premium license.
MULTI_ORG_ENABLED = get_from_env("MULTI_ORG_ENABLED", False, type_cast=str_to_bool)

BILLING_V2_ENABLED = get_from_env("BILLING_V2_ENABLED", False, type_cast=str_to_bool)

AUTO_LOGIN = get_from_env("AUTO_LOGIN", False, type_cast=str_to_bool)

CONTAINER_HOSTNAME = os.getenv("HOSTNAME", "unknown")

PROM_PUSHGATEWAY_ADDRESS = os.getenv("PROM_PUSHGATEWAY_ADDRESS", None)

# Extend and override these settings with EE's ones
if "ee.apps.EnterpriseConfig" in INSTALLED_APPS:
    from ee.settings import *  # noqa: F401, F403
