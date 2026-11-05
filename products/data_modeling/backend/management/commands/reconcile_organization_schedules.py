from django.core.management.base import BaseCommand, CommandError

from products.data_modeling.backend.logic.schedule_reconcile import (
    OrganizationReconcileError,
    reconcile_organization_dags,
)


class Command(BaseCommand):
    help = (
        "Move each organization's tier schedules onto its current cadences and plan floor. Use it after a "
        "change to the refresh floor flag or a plan change whose reconcile did not run. Unlike "
        "batch_reconcile_teams it seeds no targets, and it leaves DAGs with no schedule or a whole-DAG "
        "legacy schedule as they are."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization-ids", type=str, required=True, help="Comma-separated organization ids, processed in order"
        )

    def handle(self, *args, **options):
        failed: list[str] = []
        for organization_id in options["organization_ids"].split(","):
            try:
                reconcile_organization_dags(organization_id)
            except OrganizationReconcileError as error:
                self.stderr.write(str(error))
                failed.append(organization_id)
            else:
                self.stdout.write(f"Organization {organization_id}: reconciled")
        if failed:
            raise CommandError(f"{len(failed)} organizations failed to reconcile: {','.join(failed)}")
