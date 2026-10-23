import typing

from rest_framework import serializers

from . import validation


class HTTPDestinationSerializer(validation.DestinationValidationSerializer):
    def validate(self, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
        attrs = super().validate(attrs)
        # SSRF protection for HTTP batch exports
        url = self.get_merged_config(attrs).get("url")
        if url and url not in ("https://us.i.posthog.com/batch/", "https://eu.i.posthog.com/batch/"):
            raise serializers.ValidationError(f"Invalid destination URL: {url}")
        return attrs
