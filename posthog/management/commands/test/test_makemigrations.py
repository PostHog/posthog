import sys
import importlib

from django.apps import apps
from django.core.checks.commands import migrate_and_makemigrations_autodetector
from django.core.management.commands.makemigrations import Command as DjangoMakeMigrationsCommand

from posthog.management.migration_autodetector import PostHogAutodetector

COMMAND_MODULE = "posthog.management.commands.makemigrations"


def test_migrate_checks_pass_without_the_dev_only_linear_migrations_package(monkeypatch) -> None:
    is_installed = apps.is_installed
    monkeypatch.setattr(apps, "is_installed", lambda name: name != "django_linear_migrations" and is_installed(name))
    monkeypatch.setitem(sys.modules, "django_linear_migrations.management.commands.makemigrations", None)
    try:
        command = importlib.reload(importlib.import_module(COMMAND_MODULE)).Command

        assert command.__mro__[1] is DjangoMakeMigrationsCommand
        assert command.autodetector is PostHogAutodetector
        assert migrate_and_makemigrations_autodetector() == []
    finally:
        monkeypatch.undo()
        importlib.reload(importlib.import_module(COMMAND_MODULE))
