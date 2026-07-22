"""URL configuration for the Customer analytics external API."""

from django.urls import path

from products.customer_analytics.backend.presentation.views.external import (
    ExternalAccountCustomPropertiesView,
    ExternalAccountListView,
    ExternalAccountView,
)

urlpatterns = [
    path("external/account", ExternalAccountView.as_view(), name="external-account"),
    path("external/accounts", ExternalAccountListView.as_view(), name="external-account-list"),
    path(
        "external/account/custom_property_values",
        ExternalAccountCustomPropertiesView.as_view(),
        name="external-account-custom-property-values",
    ),
]
