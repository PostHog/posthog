import os

from posthog.settings.utils import get_from_env

CONTINUOUS_PROFILING_ENABLED: bool = get_from_env("CONTINUOUS_PROFILING_ENABLED", False, type_cast=bool)
PYROSCOPE_SERVER_ADDRESS: str = os.getenv("PYROSCOPE_SERVER_ADDRESS", "")
PYROSCOPE_APPLICATION_NAME: str = os.getenv("PYROSCOPE_APPLICATION_NAME", "")
PYROSCOPE_SAMPLE_RATE: int = get_from_env("PYROSCOPE_SAMPLE_RATE", 100, type_cast=int)
