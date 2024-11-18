import os

import pytest

from posthog.demo.matrix.manager import MatrixManager
from posthog.tasks.demo_create_data import HedgeboxMatrix
from posthog.test.base import BaseTest


@pytest.mark.skipif(os.environ.get("DEEPEVAL") != "YES", reason="Only runs for the assistant evaluation")
@pytest.mark.django_db(transaction=True)
class EvalBaseTest(BaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        matrix = HedgeboxMatrix(days_past=45, days_future=1, n_clusters=30, group_type_index_offset=0)
        matrix_manager = MatrixManager(matrix, print_steps=True)
        existing_user = cls.team.organization.members.first()
        matrix_manager.run_on_team(cls.team, existing_user)
