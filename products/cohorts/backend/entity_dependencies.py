from posthog.models.entity_dependencies.registry import DependencyResolver, register_resolver
from posthog.models.entity_dependencies.types import EntityRef, EntityRefStatus

from products.cohorts.backend.models.cohort import Cohort


class CohortDependencyResolver(DependencyResolver):
    entity_type = "cohort"

    def resolve(self, team_id: int, ids: list[str]) -> dict[str, EntityRef]:
        numeric_ids = [int(entity_id) for entity_id in ids if entity_id.isdigit()]
        if not numeric_ids:
            return {}
        refs: dict[str, EntityRef] = {}
        for cohort in Cohort.objects.filter(team_id=team_id, pk__in=numeric_ids).only("id", "name", "deleted"):
            refs[str(cohort.pk)] = EntityRef(
                type="cohort",
                id=str(cohort.pk),
                name=cohort.name or "",
                url=f"/cohorts/{cohort.pk}",
                status=EntityRefStatus.DELETED if cohort.deleted else EntityRefStatus.ACTIVE,
            )
        return refs


register_resolver(CohortDependencyResolver())
