"""Cause git to detect a merge conflict when two branches have migrations."""

from django.core.management.commands.makemigrations import (
    Command as MakeMigrationsCommand,
)
from django.db.migrations.loader import MigrationLoader


class Command(MakeMigrationsCommand):
    def handle(self, *app_labels, **options):
        # Generate a migrations manifest with latest migration on each app
        super(Command, self).handle(*app_labels, **options)

        loader = MigrationLoader(None, ignore_no_migrations=True)
        apps = sorted(loader.migrated_apps)
        graph = loader.graph

        with open("latest_migrations.manifest", "w", encoding="utf_8") as f:
            for app_name in apps:
                leaf_nodes = graph.leaf_nodes(app_name)
                if len(leaf_nodes) != 1:
                    raise Exception("App {} has multiple leaf migrations!".format(app_name))
                f.write("{}: {}\n".format(app_name, leaf_nodes[0][1]))
