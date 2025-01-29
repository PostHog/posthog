from posthog.settings.utils import get_from_env

HUGGINGFACE_API_KEY = get_from_env("HUGGINGFACE_API_KEY", None)
TOGETHER_API_KEY = get_from_env("TOGETHER_API_KEY", None)
