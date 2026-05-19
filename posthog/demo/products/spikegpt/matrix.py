from posthog.demo.matrix.matrix import Cluster, Matrix
from posthog.models import Cohort

from .models import SpikeGPTPerson


class SpikeGPTCluster(Cluster):
    matrix: "SpikeGPTMatrix"

    MIN_RADIUS: int = 0
    MAX_RADIUS: int = 0

    def __str__(self) -> str:
        return f"Social Circle #{self.index + 1}"

    def radius_distribution(self) -> float:
        return self.random.betavariate(1.5, 5)

    def initiation_distribution(self) -> float:
        return self.random.betavariate(1.8, 1)


class SpikeGPTMatrix(Matrix):
    PRODUCT_NAME = "SpikeGPT"
    CLUSTER_CLASS = SpikeGPTCluster
    PERSON_CLASS = SpikeGPTPerson

    def set_project_up(self, team, user):
        super().set_project_up(team, user)

        # Cohorts
        Cohort.objects.create(
            team=team,
            name="Signed-up users",
            created_by=user,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "is_set",
                            "operator": "is_set",
                        }
                    ]
                }
            ],
        )
        # Create the standard internal/test users cohort (same as non-demo teams get)
        from posthog.models.cohort.cohort import get_or_create_internal_test_users_cohort

        test_users_cohort = get_or_create_internal_test_users_cohort(team, initiating_user_email=user.email)
        team.test_account_filters = [
            {"key": "id", "type": "cohort", "value": test_users_cohort.pk, "operator": "not_in"},
        ]
