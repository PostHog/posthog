from django.db import transaction


def demo_reset_master_team() -> None:
    # Deferred: the demo matrix pulls mimesis (fake-data generator); this module is
    # eager-imported by posthog/tasks/__init__, so a module-level import drags it onto startup.
    from products.demo.backend.facade.api import HedgeboxMatrix, MatrixManager  # noqa: PLC0415

    matrix = HedgeboxMatrix()
    manager = MatrixManager(matrix)
    with transaction.atomic():
        manager.reset_master()
