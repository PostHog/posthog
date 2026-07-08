"""Wiring for the data_modeling_ops internal (service-to-service) API.

Core URL routing and sibling products import the viewset and auth primitives from
here rather than reaching into presentation modules. Only imported by posthog/urls.py
(request time) and the endpoints product, so the DRF dependencies stay off the
``django.setup()`` path.
"""

from products.data_modeling.backend.presentation.internal_auth import (
    DataModelingOpsAuthenticationMixin,
    DataModelingOpsOIDCAuthentication,
)
from products.data_modeling.backend.presentation.internal_views import InternalDataModelingOpsViewSet

__all__ = [
    "DataModelingOpsAuthenticationMixin",
    "DataModelingOpsOIDCAuthentication",
    "InternalDataModelingOpsViewSet",
]
