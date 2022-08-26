from django.conf import settings
from django.db import transaction

from posthog.demo.matrix import MatrixManager
from posthog.demo.products import HedgeboxMatrix


def demo_reset_master_team() -> None:
    matrix = HedgeboxMatrix(n_clusters=settings.DEMO_MATRIX_N_CLUSTERS)
    manager = MatrixManager(matrix)
    with transaction.atomic():
        manager.reset_master()
