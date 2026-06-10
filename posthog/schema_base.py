"""Base class for the generated ``posthog.schema`` models (see bin/build-schema-python.sh).

``defer_build`` postpones each model's pydantic core-schema and validator construction from
class creation — where ``django.setup()`` pays it for every model in the module — to the
model's first validation/serialization. Importing ``posthog.schema`` is on the startup path
of every process, while most processes touch only a fraction of the models.

The exception is web: there a deferred build would land on a live request (the first
``/query`` validation builds the whole discriminated-union tree, once per worker), so the
web entrypoints (wsgi.py / asgi.py) set ``POSTHOG_BUILD_SCHEMA_MODELS_AT_IMPORT`` before the
app loads and get the eager behavior — paid at boot, behind the readiness probe, pre-fork so
workers share the built validators copy-on-write. Building eagerly at class creation is also
~2x cheaper than post-hoc ``model_rebuild()`` calls, which is why this is an import-time
switch rather than a warm-up loop.
"""

import os

from pydantic import BaseModel, ConfigDict

_defer = os.environ.get("POSTHOG_BUILD_SCHEMA_MODELS_AT_IMPORT") != "1"


class SchemaBaseModel(BaseModel):
    model_config = ConfigDict(defer_build=_defer)
