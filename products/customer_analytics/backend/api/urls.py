"""URL configuration for the Customer analytics external API."""

from django.urls import path

from .external import ExternalAccountView

urlpatterns = [
    path("external/account", ExternalAccountView.as_view(), name="external-account"),
]
