import datetime as dt
import os

import pytest
from flaky import flaky

from posthog.demo.matrix.manager import MatrixManager
from posthog.tasks.demo_create_data import HedgeboxMatrix
from posthog.test.base import BaseTest


@pytest.mark.skipif(os.environ.get("DEEPEVAL") != "YES", reason="Only runs for the assistant evaluation")
@flaky(max_runs=3, min_passes=1)
@pytest.mark.django_db(transaction=True)
class EvalBaseTest(BaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        matrix = HedgeboxMatrix(
            now=dt.datetime.now(dt.UTC) - dt.timedelta(days=15),
            days_past=21,
            days_future=14,
            n_clusters=30,
            group_type_index_offset=0,
        )
        matrix_manager = MatrixManager(matrix, print_steps=True)
        existing_user = cls.team.organization.members.first()
        matrix_manager.run_on_team(cls.team, existing_user)
