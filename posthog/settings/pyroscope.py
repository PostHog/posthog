import os

import pyroscope

from posthog.settings import get_from_env
from posthog.settings.base_variables import TEST


def pyroscope_init() -> None:
    if not TEST and os.getenv("PYROSCOPE_TOKEN"):
        sample_rate = get_from_env("PYROSCOPE_SAMPLE_RATE", type_cast=int, default=100)

        pyroscope.configure(
            application_name=os.getenv("PYROSCOPE_APP_NAME", "posthog"),
            server_address=os.getenv("PYROSCOPE_ADDRESS", "https://ingest.pyroscope.cloud"),
            auth_token=os.environ["PYROSCOPE_TOKEN"],
            sample_rate=sample_rate,
            detect_subprocesses=True,  # detect subprocesses started by the main process
            oncpu=True,  # report cpu time only
            native=True,  # profile native extensions
            gil_only=False,  # only include traces for threads that are holding on to the GIL
        )


pyroscope_init()
