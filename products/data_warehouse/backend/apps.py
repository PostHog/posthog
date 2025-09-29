from django.apps import AppConfig


class DataWarehouseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.data_warehouse.backend"
    label = "data_warehouse"
