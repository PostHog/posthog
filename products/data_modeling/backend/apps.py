from django.apps import AppConfig


class DataModelingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.data_modeling.backend"
    label = "data_modeling"
