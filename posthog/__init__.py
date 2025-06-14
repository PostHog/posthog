import sys
from unittest.mock import MagicMock
import deltalake.writer

# DLT imports the missing function `try_get_deltatable` from `deltalake` which
# it doesn't actually use but also no longer exists. So we can safely mock
# it to allow the app to startup without module errors
deltalake.writer.try_get_deltatable = MagicMock()  # type: ignore
sys.modules["deltalake.writer"] = deltalake.writer


# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
from posthog.celery import app as celery_app  # noqa: E402

__all__ = ("celery_app",)

# snowflake-connector-python tries to access a root folder which errors out in pods.
# This sets the snowflake home directory to a relative folder
import os  # noqa: E402

os.environ["SNOWFLAKE_HOME"] = "./.snowflake"
