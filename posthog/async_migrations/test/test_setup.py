import pytest

from django.apps import apps
from django.db import connection
from django.db.models.signals import post_migrate
from django.test.utils import CaptureQueriesContext

pytestmark = pytest.mark.async_migrations


def test_app_ready_makes_no_db_queries(db):
    posthog_config = apps.get_app_config("posthog")
    with CaptureQueriesContext(connection) as ctx:
        posthog_config.ready()
    queries = [q["sql"][:160] for q in ctx.captured_queries]
    assert len(ctx.captured_queries) == 0, (
        f"PostHogConfig.ready() must not issue DB queries -- async migration setup "
        f"runs via post_migrate signal instead. Got {len(ctx.captured_queries)} "
        f"queries: {queries}"
    )


def test_post_migrate_invokes_async_migration_setup(db, settings, mocker):
    settings.SKIP_ASYNC_MIGRATIONS_SETUP = False
    mock_setup = mocker.patch("posthog.async_migrations.setup.setup_async_migrations")
    posthog_config = apps.get_app_config("posthog")
    post_migrate.send(
        sender=posthog_config,
        app_config=posthog_config,
        verbosity=0,
        interactive=False,
        using="default",
    )
    mock_setup.assert_called_once()


def test_post_migrate_respects_skip_env_var(db, settings, mocker):
    settings.SKIP_ASYNC_MIGRATIONS_SETUP = True
    mock_setup = mocker.patch("posthog.async_migrations.setup.setup_async_migrations")
    posthog_config = apps.get_app_config("posthog")
    post_migrate.send(
        sender=posthog_config,
        app_config=posthog_config,
        verbosity=0,
        interactive=False,
        using="default",
    )
    mock_setup.assert_not_called()
