import orjson
from pydantic import BaseModel
from rest_framework.utils.encoders import JSONEncoder


def to_json(query: BaseModel) -> bytes:
    instance_dict = query.model_construct(**query.model_dump(exclude_none=True, exclude_defaults=False)).model_dump(
        exclude_none=True
    )

    option = orjson.OPT_SORT_KEYS
    json_string = orjson.dumps(instance_dict, default=JSONEncoder().default, option=option)

    return json_string
