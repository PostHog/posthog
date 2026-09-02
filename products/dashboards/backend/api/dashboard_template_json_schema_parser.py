# parsers.py
import json
from pathlib import Path

import jsonschema
from jsonschema.exceptions import SchemaError
from rest_framework.exceptions import ValidationError

from posthog.parsers import SafeJSONParser

dashboard_template_schema = json.loads((Path(__file__).parent / "dashboard_template_schema.json").read_text())


class DashboardTemplateCreationJSONSchemaParser(SafeJSONParser):
    """On DashboardTemplate creation, validate the JSON against a JSON schema.
    The template is sent in the "template" key"""

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type or "application/json", parser_context)
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
