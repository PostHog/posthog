import codecs

from pydantic import BaseModel, ValidationError
from django.conf import settings

from rest_framework.parsers import JSONParser
from rest_framework.exceptions import ParseError


class PydanticJSONParser(JSONParser):
    """
    Parses JSON-serialized data using Pydantic.
    """

    def parse(self, stream, media_type=None, parser_context=None):
        """
        Parses the incoming bytestream as JSON and returns the resulting data.

        The view needs a pydantic_models attribute with a dictionary of action names to pydantic models.
        This is needed because otherwise the parser doesn't know which model to use.
        """
        pydantic_model: type[BaseModel] = getattr(parser_context["view"], "pydantic_models", {}).get(
            parser_context["view"].action, None
        )
        if not pydantic_model:
            return super().parse(stream, media_type, parser_context)

        parser_context = parser_context or {}
        encoding = parser_context.get("encoding", settings.DEFAULT_CHARSET)
        decoded_stream = codecs.getreader(encoding)(stream)

        try:
            return pydantic_model.model_validate_json(decoded_stream.read())
        except ValidationError as exc:
            raise ParseError("JSON parse error - %s" % str(exc))
