from django.apps import AppConfig


class CdpConfig(AppConfig):
    # Legacy Plugin/HogFunction/Hook tables used AutoField (INT4) before BigAutoField
    # became Django's default. SeparateDatabaseAndState preserves the DB schema, so the
    # app default must match — otherwise fresh test DBs would create INT8 columns and
    # break clients that decode the id as i32 (notably the feature-flags Rust service).
    default_auto_field = "django.db.models.AutoField"
    name = "products.cdp.backend"
    label = "cdp"
