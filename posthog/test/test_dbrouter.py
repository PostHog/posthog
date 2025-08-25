from posthog.test.base import BaseTest

from posthog.dbrouter import ReplicaRouter
from posthog.models.team import Team
from posthog.models.user import User


class TestReplicaRouter(BaseTest):
    def test_opted_in_models_are_replica_routed(self) -> None:
        router = ReplicaRouter(["User"])

        self.assertEqual(router.db_for_write(User), "default")

        self.assertEqual(router.db_for_read(User), "replica")
        self.assertEqual(router.db_for_read(Team), "default")  # not opted in = not routed
