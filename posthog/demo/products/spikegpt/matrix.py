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
        real_users_cohort = Cohort.objects.create(
            team=team,
            name="Real persons",
            description="People who don't belong to the SpikeGPT team.",
            created_by=user,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@spikegpt.com$",
                            "operator": "not_regex",
                        }
                    ]
                }
            ],
        )
        team.test_account_filters = [{"key": "id", "type": "cohort", "value": real_users_cohort.pk}]
