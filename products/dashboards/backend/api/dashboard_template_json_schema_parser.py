# parsers.py
import json
from pathlib import Path

import jsonschema
from jsonschema.exceptions import SchemaError
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser

dashboard_template_schema = json.loads((Path(__file__).parent / "dashboard_template_schema.json").read_text())


class DashboardTemplateCreationJSONSchemaParser(JSONParser):
    """On DashboardTemplate creation, validate the JSON against a JSON schema.
    The template is sent in the "template" key"""

    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type or "application/json", parser_context)
        # A body without a "template" key used to reach the view and raise KeyError there, so a malformed
        # request answered with a 500 instead of telling the client what was wrong.
        if not isinstance(data, dict) or "template" not in data:
            raise ValidationError(detail="Invalid JSON: must provide a 'template' key")
        try:
            jsonschema.validate(data["template"], dashboard_template_schema)
        except ValueError as error:
            raise ValidationError(detail=f"Invalid JSON: {error}")
        except SchemaError as error:
            raise ValidationError(detail=str(error))
        except jsonschema.exceptions.ValidationError as error:
            raise ValidationError(detail=str(error))
        else:
            return data
