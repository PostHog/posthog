from collections import defaultdict
from typing import Any

from django.core.management.base import BaseCommand
from django.db.models import IntegerField, Model

from products.access_control.backend.facade.object_names import model_has_field, resources_with_object_access_controls
from products.access_control.backend.models.access_control import AccessControl


class Command(BaseCommand):
    help = "Delete object access rules whose object was soft-deleted before rules were dropped on deletion"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report only, delete nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        total = 0
        for resource, models in sorted(resources_with_object_access_controls().items()):
            rule_ids = self._stale_rule_ids(resource, [m for m in models if model_has_field(m, "deleted")])
            if not rule_ids:
                continue
            total += len(rule_ids)
            self.stdout.write(f"{resource}: {len(rule_ids)} rules on deleted objects")
            if not options["dry_run"]:
                AccessControl.objects.filter(id__in=rule_ids).delete()
        verb = "would be deleted" if options["dry_run"] else "deleted"
        self.stdout.write(f"{total} rules {verb}")

    def _stale_rule_ids(self, resource: str, models: list[type[Model]]) -> list[Any]:
        rules = AccessControl.objects.filter(resource=resource, resource_id__isnull=False)
        by_team_and_object: dict[tuple[int, str], list[Any]] = defaultdict(list)
        for rule_id, team_id, resource_id in rules.values_list("id", "team_id", "resource_id"):
            by_team_and_object[(team_id, resource_id)].append(rule_id)
        stale: list[Any] = []
        for model in models:
            pks = {resource_id for _, resource_id in by_team_and_object}
            if isinstance(model._meta.pk, IntegerField):
                pks = {pk for pk in pks if pk.isdigit()}
            # _base_manager so deleted rows are visible; rules address objects by pk as a string
            deleted = model._base_manager.filter(deleted=True, pk__in=pks).values_list("team_id", "pk")
            for team_id, pk in deleted:
                stale.extend(by_team_and_object.get((team_id, str(pk)), []))
        return stale
