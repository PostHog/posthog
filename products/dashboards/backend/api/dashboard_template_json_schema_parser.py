# parsers.py
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema.exceptions import SchemaError
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser

dashboard_template_schema = json.loads((Path(__file__).parent / "dashboard_template_schema.json").read_text())


def validate_dashboard_template_creation_body(data: Any) -> None:
    """DRF skips the parser and sets an empty `request.data` for a zero-byte body,
    so each action that reads `data["template"]` must check the shape itself."""
    if not isinstance(data, Mapping) or "template" not in data:
        raise ValidationError(detail="Request body must be a JSON object with a 'template' key")


class DashboardTemplateCreationJSONSchemaParser(JSONParser):
    """On DashboardTemplate creation, validate the JSON against a JSON schema.
    The template is sent in the "template" key"""

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type or "application/json", parser_context)
        validate_dashboard_template_creation_body(data)
        try:
            template = data["template"]
            jsonschema.validate(template, dashboard_template_schema)
        except ValueError as error:
            raise ValidationError(detail=f"Invalid JSON: {error}")
        except SchemaError as error:
            raise ValidationError(detail=str(error))
        except jsonschema.exceptions.ValidationError as error:
            raise ValidationError(detail=str(error))
        else:
            return data
