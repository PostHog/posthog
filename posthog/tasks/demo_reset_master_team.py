from django.db import transaction


def demo_reset_master_team() -> None:
    # Deferred: the demo matrix pulls mimesis (fake-data generator); this module is
    # eager-imported by posthog/tasks/__init__, so a module-level import drags it onto startup.
    from products.demo.backend.matrix import MatrixManager  # noqa: PLC0415
    from products.demo.backend.products import HedgeboxMatrix  # noqa: PLC0415

    matrix = HedgeboxMatrix()
    manager = MatrixManager(matrix)
    with transaction.atomic():
        manager.reset_master()
