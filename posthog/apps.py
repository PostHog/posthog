import os

from django.apps import AppConfig
from django.conf import settings

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from posthoganalytics.client import Client

from posthog.git import get_git_branch, get_git_commit_short
from posthog.utils import (
    _build_flag_provider,
    get_available_timezones_with_offsets,
    get_instance_region,
    get_machine_id,
    initialize_self_capture_api_token,
    str_to_bool,
)

logger = structlog.get_logger(__name__)


class PostHogConfig(AppConfig):
    name = "posthog"
    verbose_name = "PostHog"

    def ready(self):
        # Route all JSONField (jsonb) decode through orjson before any query runs.
        if settings.JSONFIELD_ORJSON_DECODE:
            from posthog.helpers.orjson_jsonfield import apply as apply_orjson_jsonfield  # noqa: PLC0415

            apply_orjson_jsonfield()

        import posthog.storage.team_access_cache_signal_handlers  # noqa: F401
        from posthog.storage.gateway_credential_signal_handlers import (
            connect_signal_handlers as connect_gateway_credential_signal_handlers,
        )
        from posthog.storage.team_llm_gateway_policy_signal_handlers import connect_signal_handlers

        connect_signal_handlers()
        connect_gateway_credential_signal_handlers()

        # Connect core signal receivers at app-population. They used to wire in as an import
        # side effect of viewset modules; with the lazy API router those no longer load at
        # django.setup(), so a process that never builds the router (celery, temporal, migrate,
        # shell) would lose them. They live in dedicated import-light modules — never wire
        # ready() through an API module, even one that looks light today.
        import posthog.storage.checks  # noqa: F401, PLC0415
        import posthog.caching.organization_serializer_cache  # noqa: F401, PLC0415
        import posthog.models.activity_logging.signal_handlers  # noqa: F401, PLC0415

        if settings.COMMAND_EXEC_AUDIT_ENABLED:
            from posthog.security.command_exec_audit import install as install_command_exec_audit  # noqa: PLC0415

            install_command_exec_audit()

        self._setup_lazy_admin()
        self._prewarm_timezone_offsets_cache()
        posthoganalytics.api_key = "sTMFPsFhdP1Ssg"  # ty: ignore[invalid-assignment]
        # Fall back to DEV_API_KEY in debug so feature flags work locally without manual env setup.
        # DEV_API_KEY lives in ee/settings.py — getattr returns None in OSS mode.
        posthoganalytics.personal_api_key = os.environ.get(
            "POSTHOG_PERSONAL_API_KEY",
            getattr(settings, "DEV_API_KEY", None) if settings.DEBUG else None,
        )
        posthoganalytics.poll_interval = 90  # ty: ignore[invalid-assignment]
        posthoganalytics.enable_exception_autocapture = True  # ty: ignore[invalid-assignment]
        posthoganalytics.log_captured_exceptions = True  # ty: ignore[invalid-assignment]
        posthoganalytics.super_properties = {  # ty: ignore[invalid-assignment]
            "region": get_instance_region(),
            "service": settings.OTEL_SERVICE_NAME,
            "environment": os.getenv("OTEL_SERVICE_ENVIRONMENT"),
        }

        if str_to_bool(os.environ.get("TEMPORAL_DISABLE_EXCEPTION_VARIABLE_CAPTURE", "false")):
            posthoganalytics.capture_exception_code_variables = False
        else:
            posthoganalytics.capture_exception_code_variables = True  # ty: ignore[invalid-assignment]

        if settings.E2E_TESTING:
            posthoganalytics.api_key = "phc_ex7Mnvi4DqeB6xSQoXU1UVPzAmUIpiciRKQQXGGTYQO"  # ty: ignore[invalid-assignment]
            posthoganalytics.personal_api_key = None
        elif settings.TEST or os.environ.get("OPT_OUT_CAPTURE", False):
            posthoganalytics.disabled = True  # ty: ignore[invalid-assignment]
        elif settings.DEBUG:
            # In dev, analytics is by default turned to self-capture, i.e. data going into this very instance of PostHog
            # Due to ASGI's workings, we can't query for the right project token in this `ready()` method
            # Instead, we configure self-capture with `self_capture_wrapper()` in posthog/asgi.py - see that file
            # Self-capture for WSGI is initialized here
            posthoganalytics.disabled = True  # ty: ignore[invalid-assignment]
            logger.info(
                "posthog_config_ready",
                settings_debug=settings.DEBUG,
                server_gateway_interface=settings.SERVER_GATEWAY_INTERFACE,
            )
            if settings.SERVER_GATEWAY_INTERFACE == "WSGI":
                async_to_sync(initialize_self_capture_api_token)()

            # log development server launch to posthog
            if os.getenv("RUN_MAIN") == "true":
                # posthog.tasks.__init__ is a celery autoimport aggregator: importing any
                # submodule loads every task module. Keep that off django.setup() for all
                # processes; celery workers get it via autodiscover_tasks().
                from posthog.tasks.tasks import sync_all_organization_available_product_features  # noqa: PLC0415

                # Sync all organization.available_product_features once on launch, in case plans changed
                sync_all_organization_available_product_features()

                # NOTE: This has to be created as a separate client so that the "capture" call doesn't lock in the properties
                phcloud_client = Client(posthoganalytics.api_key)

                phcloud_client.capture(
                    distinct_id=get_machine_id(),
                    event="development server launched",
                    properties={"git_rev": get_git_commit_short(), "git_branch": get_git_branch()},
                )
        # Use HyperCache to provide flag definitions instead of per-process API polling.
        # Falls back to the SDK's emergency API fetch (via personal_api_key) only when
        # the cache is cold. In E2E testing personal_api_key is None, so a cold cache
        # will result in no flag definitions being loaded — which is acceptable there.
        if not posthoganalytics.disabled:
            posthoganalytics.flag_definition_cache_provider = _build_flag_provider()  # ty: ignore[invalid-assignment]

        # load feature flag definitions if not already loaded
        if not posthoganalytics.disabled and posthoganalytics.feature_flag_definitions() is None:
            posthoganalytics.load_feature_flags()

        from posthog.async_migrations.setup import setup_async_migrations_with_retry

        if settings.SKIP_ASYNC_MIGRATIONS_SETUP:
            logger.warning("Skipping async migrations setup. This is unsafe in production!")
        else:
            # Tolerate transient Postgres unreachability at boot instead of crash-looping.
            setup_async_migrations_with_retry()

        from posthog.api.file_system import registrations as file_system_registrations

        from products.cdp.backend.tasks.hog_functions import queue_sync_hog_function_templates

        # Skip during tests since we handle this in conftest.py
        # Skip during collectstatic (STATIC_COLLECTION=1 in Dockerfile) — no Redis available at build time
        if not settings.TEST and not settings.STATIC_COLLECTION:
            queue_sync_hog_function_templates()

        file_system_registrations.register_core_file_system_types()

    def _prewarm_timezone_offsets_cache(self):
        # The pytz walk in get_available_timezones_with_offsets is hourly-cached but
        # the cache is per-process. Without pre-warming, every fresh pod pays ~580ms
        # on its first preflight (the home view). Run it once at startup so the cache
        # is hot before any request lands. Skip during tests / static collection where
        # this would just slow setup with no benefit.
        if settings.TEST or settings.STATIC_COLLECTION:
            return
        try:
            get_available_timezones_with_offsets()
        except Exception:
            logger.warning("prewarm_timezone_offsets_cache_failure", exc_info=True)

    def _setup_lazy_admin(self):
        """Set up lazy loading of admin classes to avoid importing all at startup."""
        import sys

        from django.contrib import admin

        class LazyAdminRegistry(dict):
            """Lazy admin registry that loads admin on first access."""

            _loaded = False

            def _ensure_loaded(self):
                if not self._loaded:
                    from posthog.admin import register_all_admin

                    self._loaded = True
                    register_all_admin()

            # `dict.items()`, `dict.values()`, and `dict.keys()` iterate the
            # underlying storage at the C level — they DO NOT call `__iter__`
            # or `__getitem__`. Django admin's `AdminSite.get_urls()` and
            # `_build_app_dict()` use `self._registry.items()` /
            # `self._registry.values()`, so without explicit overrides the
            # lazy load never fires from those code paths and admin URLs /
            # sidebar entries silently come back empty.
            #
            # Read methods are listed out explicitly rather than wrapped via
            # metaprogramming. The set is small, exhaustive against what
            # Django's admin actually calls, and grep-friendly. Wrapping
            # every dict method via `__getattribute__` or a class-time loop
            # would also have to carefully skip the write methods
            # (`__setitem__`, `__delitem__`) that `register_all_admin()`
            # depends on, plus our own `_ensure_loaded` / `_loaded` — adding
            # recursion footguns without removing real boilerplate.
            def __getitem__(self, key):
                self._ensure_loaded()
                return super().__getitem__(key)

            def __iter__(self):
                self._ensure_loaded()
                return super().__iter__()

            def __len__(self):
                self._ensure_loaded()
                return super().__len__()

            def __contains__(self, key):
                self._ensure_loaded()
                return super().__contains__(key)

            def keys(self):
                self._ensure_loaded()
                return super().keys()

            def values(self):
                self._ensure_loaded()
                return super().values()

            def items(self):
                self._ensure_loaded()
                return super().items()

            def get(self, key, default=None):
                self._ensure_loaded()
                return super().get(key, default)

        # Don't use lazy loading in tests and migrations
        if not settings.TEST and "migrate" not in sys.argv and "test" not in sys.argv:
            # Wrap the existing _registry rather than overwriting it. With
            # `SimpleAdminConfig` the dict is normally empty here (Django's
            # autodiscover is deferred to inside `register_all_admin()`), but
            # a third-party `AppConfig.ready()` could populate it before
            # `PostHogConfig.ready()` runs. The dict-copy constructor preserves
            # any such entries and only adds lazy-load semantics on top.
            admin.site._registry = LazyAdminRegistry(admin.site._registry)

        # Install the OAuth sidebar regrouping override eagerly. It must wrap
        # `get_app_list` before the first admin request — if it were installed
        # from inside `register_all_admin()` it would only land mid-call, after
        # the original method had already started executing.
        from posthog.admin import install_admin_app_list_overrides

        install_admin_app_list_overrides()
