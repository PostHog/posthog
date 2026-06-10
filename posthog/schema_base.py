"""Base class for the generated ``posthog.schema`` models (see bin/build-schema-python.sh).

``defer_build`` postpones each model's pydantic core-schema and validator construction from
class creation — where ``django.setup()`` pays it for every model in the module — to the
model's first validation/serialization. Importing ``posthog.schema`` is on the startup path
of every process, while any single process touches only a fraction of the models.
"""

from pydantic import BaseModel, ConfigDict


class SchemaBaseModel(BaseModel):
    model_config = ConfigDict(defer_build=True)
