from __future__ import annotations

import logging

from django.utils.crypto import get_random_string
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import viewsets
from django.core.cache import cache
from rest_framework import serializers

logger = logging.getLogger("sentry.api")
SETUP_WIZARD_CACHE_PREFIX = "setup-wizard-keys:v1:"
SETUP_WIZARD_CACHE_TIMEOUT = 600


class SetupWizardSerializer(serializers.Serializer):
    hash = serializers.CharField()

    def to_representation(self, instance: str) -> dict[str, str]:
        return {"hash": instance}

    def create(self) -> dict[str, str]:
        hash = get_random_string(64, allowed_chars="abcdefghijklmnopqrstuvwxyz012345679")
        key = f"{SETUP_WIZARD_CACHE_PREFIX}{hash}"

        cache.set(key, {"project_id": None, "personal_api_key": None}, SETUP_WIZARD_CACHE_TIMEOUT)

        return {"hash": hash}


class SetupWizardViewSet(viewsets.ViewSet):
    permission_classes = ()
    lookup_field = "hash"
    lookup_url_kwarg = "hash"

    def destroy(self, request: Request, hash=None) -> Response | None:
        """
        This removes the cache content for a specific hash
        """
        if hash is not None:
            key = f"{SETUP_WIZARD_CACHE_PREFIX}{hash}"
            cache.delete(key)
            return Response(status=200)
        return None

    def list(self, request: Request, hash=None) -> Response:
        """
        This tries to retrieve and return the cache content if possible
        otherwise creates new cache
        """

        hash = request.query_params.get("hash")

        if hash is not None:
            # key = f"{SETUP_WIZARD_CACHE_PREFIX}{hash}"
            # wizard_data = cache.get(key)

            wizard_data = {
                "project_api_key": "test_api_key",
            }

            if wizard_data is None:
                return Response(status=404)
            elif wizard_data == "empty":
                # when we just created a clean cache
                return Response(status=400)

            return Response(wizard_data)
        else:
            # TODO: Handle rate limiting per IP address

            serializer = SetupWizardSerializer()
            return Response(serializer.create())
