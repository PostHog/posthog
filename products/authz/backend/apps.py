"""Django app configuration for authz."""

from django.apps import AppConfig


class AuthzConfig(AppConfig):
    name = "products.authz.backend"
    label = "authz"
