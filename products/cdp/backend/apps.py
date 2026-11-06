from django.apps import AppConfig


class CdpConfig(AppConfig):
    # Legacy Plugin/HogFunction/Hook tables used AutoField (INT4) before BigAutoField
    # became Django's default. SeparateDatabaseAndState preserves the DB schema, so the
    # app default must match — otherwise fresh test DBs would create INT8 columns and
    # break clients that decode the id as i32 (notably the feature-flags Rust service).
    default_auto_field = "django.db.models.AutoField"
    name = "products.cdp.backend"
    label = "cdp"

    def ready(self) -> None:
        from products.actions.backend.facade.api import on_action_saved  # noqa: PLC0415
        from products.cdp.backend.models.hog_functions.hog_function import action_saved  # noqa: PLC0415

        # Compiled filters embed each action's matcher, so they must be rebuilt when an action is saved.
        on_action_saved(action_saved, dispatch_uid="cdp.hog_functions.action_saved")
