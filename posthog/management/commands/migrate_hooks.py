from django.core.management.base import BaseCommand
from django.core.paginator import Paginator

from posthog.models.hog_functions.hog_function import HogFunction
from posthog.plugins.plugin_server_api import reload_all_hog_functions_on_workers
from posthog.settings.ee import EE_AVAILABLE


def migrate_hooks(hook_ids: list[str], team_ids: list[int], dry_run: bool = False):
    if not EE_AVAILABLE:
        print("This command is only available in PostHog EE")  # noqa: T201
        return

    from products.enterprise.backend.api.hooks import create_zapier_hog_function
    from products.enterprise.backend.models.hook import Hook

    if hook_ids and team_ids:
        print("Please provide either hook_ids or team_ids, not both")  # noqa: T201
        return

    query = Hook.objects.select_related("team").order_by("id")

    if team_ids:
        print("Migrating all hooks for teams:", team_ids)  # noqa: T201
        query = query.filter(team_id__in=team_ids)
    elif hook_ids:
        print("Migrating hooks:", hook_ids)  # noqa: T201
        query = query.filter(id__in=hook_ids)
    else:
        print(f"Migrating all hooks")  # noqa T201

    paginator = Paginator(query.all(), 100)

    hook_ids_to_delete = []

    for page_number in paginator.page_range:
        page = paginator.page(page_number)
        hog_functions: list[HogFunction] = []

        for hook in page.object_list:
            try:
                hog_function = create_zapier_hog_function(
                    hook,
                    {
                        "user": hook.user,
                        "get_team": lambda hook=hook: hook.team,
                        "is_create": True,
                    },
                    from_migration=True,
                )
                hog_functions.append(hog_function)
            except Exception as e:
                print(f"Error migrating hook {hook.id}: {e}")  # noqa: T201
                continue

        if not dry_run:
            HogFunction.objects.bulk_create(hog_functions)
            hook_ids_to_delete.extend([hook.id for hook in page.object_list])
        else:
            print("Would have created the following HogFunctions:")  # noqa: T201
            for hog_function in hog_functions:
                print(hog_function)  # noqa: T201

    if not dry_run:
        query.filter(id__in=hook_ids_to_delete).delete()
        reload_all_hog_functions_on_workers()


class Command(BaseCommand):
    help = "Migrate zapier hooks to HogFunctions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            type=bool,
            help="If set, will not actually perform the migration, but will print out what would have been done",
        )
        parser.add_argument("--hook-ids", type=str, help="Comma separated list of hook ids to sync")
        parser.add_argument("--team-ids", type=str, help="Comma separated list of team ids to sync")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        hook_ids = options["hook_ids"]
        team_ids = options["team_ids"]

        if hook_ids and team_ids:
            print("Please provide either hook_ids or team_ids, not both")  # noqa: T201
            return

        migrate_hooks(
            hook_ids=hook_ids.split(",") if hook_ids else [],
            team_ids=[int(x) for x in team_ids.split(",")] if team_ids else [],
            dry_run=dry_run,
        )
