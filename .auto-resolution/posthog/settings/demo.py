from posthog.settings.base_variables import TEST
from posthog.settings.utils import get_from_env

DEMO_MATRIX_N_CLUSTERS = get_from_env("DEMO_MATRIX_N_CLUSTERS", 3000 if not TEST else 1, type_cast=int)
