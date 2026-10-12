"""DRF serializers for authz."""

from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import OpenFgaStatus


class OpenFgaStatusSerializer(DataclassSerializer):
    class Meta:
        dataclass = OpenFgaStatus
        extra_kwargs = {
            "reachable": {"help_text": "Whether the OpenFGA server answered every status request."},
            "api_url": {"help_text": "OpenFGA API URL that the client uses, without any user name or password."},
            "store_name": {"help_text": "Name of the OpenFGA store. Null when no store was found or OpenFGA failed."},
            "store_id": {"help_text": "ID of the OpenFGA store. Null when no store was found or OpenFGA failed."},
            "authorization_model_id": {
                "help_text": "ID of the latest authorization model in the store. Null when the store has no model "
                "or OpenFGA failed."
            },
            "error": {"help_text": "Class name of the error that made OpenFGA unreachable. Null when it is reachable."},
        }
