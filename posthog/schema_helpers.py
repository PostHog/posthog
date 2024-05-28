import orjson
from typing import Any, Literal, get_origin
from pydantic import BaseModel, model_serializer
from rest_framework.utils.encoders import JSONEncoder


def to_json(query: BaseModel) -> bytes:
    klass: Any = type(query)

    class ExtendedQuery(klass):
        @model_serializer(mode="wrap")
        def include_literals(self, next_serializer):
            """
            Our schema is generated with `Literal` fields for type, kind, etc. These
            are stripped by the `exclude_defaults=True` option, so we add them back in
            here.
            """
            dumped = next_serializer(self)
            for name, field_info in self.model_fields.items():
                if get_origin(field_info.annotation) == Literal:
                    dumped[name] = getattr(self, name)
            return dumped

    # our schema is generated, so extend the models here
    query = ExtendedQuery(**query.model_dump())

    # generate a dict from the pydantic model
    instance_dict = query.model_dump(exclude_none=True, exclude_defaults=True)

    # pydantic doesn't sort keys reliably, so use orjson to serialize to json
    option = orjson.OPT_SORT_KEYS
    json_string = orjson.dumps(instance_dict, default=JSONEncoder().default, option=option)

    return json_string
