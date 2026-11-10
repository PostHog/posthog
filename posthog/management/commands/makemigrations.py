from django.apps import apps
from django.core.management.commands.makemigrations import Command as DjangoMakeMigrationsCommand

from posthog.management.migration_autodetector import PostHogAutodetector

# django_linear_migrations is a dev dependency, installed only when DEBUG is on. Django's commands.E001
# check imports this module on every `migrate`, so production must not import that package.
BaseCommand: type[DjangoMakeMigrationsCommand] = DjangoMakeMigrationsCommand
if apps.is_installed("django_linear_migrations"):
    # posthog comes before django_linear_migrations in INSTALLED_APPS, so this command replaces
    # linear-migrations' makemigrations. Subclassing it keeps max_migration.txt up to date.
    from django_linear_migrations.management.commands.makemigrations import Command as LinearMakeMigrationsCommand

    BaseCommand = LinearMakeMigrationsCommand


class Command(BaseCommand):
    autodetector = PostHogAutodetector
