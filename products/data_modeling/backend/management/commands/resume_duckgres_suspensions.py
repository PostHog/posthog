from django.core.management.base import BaseCommand

from products.data_modeling.backend.logic.node_suspension import resume_nodes
from products.data_modeling.backend.models.data_modeling_job import DataModelingJobEngine
from products.data_modeling.backend.models.node import Node

RESUMED_BY = "resume_duckgres_suspensions"


class Command(BaseCommand):
    help = (
        "Clear duckgres-engine node suspensions so shadow materializations retry. "
        "Run after a duckgres compatibility fix deploys; suspensions for other engines are untouched."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, default=None, help="Limit to one team (default: all teams)")
        parser.add_argument("--dry-run", action="store_true", help="Only report how many nodes would be resumed")

    def handle(self, *args, **options):
        suspended_nodes = Node.objects.filter(
            properties__system__suspended__has_key=DataModelingJobEngine.DUCKGRES.value
        )
        if options["team_id"] is not None:
            suspended_nodes = suspended_nodes.filter(team_id=options["team_id"])
        count = suspended_nodes.count()
        if options["dry_run"]:
            self.stdout.write(f"Would resume {count} duckgres-suspended nodes")
            return
        resumed = resume_nodes(suspended_nodes.iterator(), by=RESUMED_BY, engine=DataModelingJobEngine.DUCKGRES.value)
        self.stdout.write(f"Resumed {resumed} of {count} duckgres-suspended nodes")
