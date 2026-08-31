"""Constants for translation module."""

import json
from pathlib import Path

# Load supported languages from shared JSON file
_LANGUAGES_JSON_PATH = Path(__file__).parent.parent.parent / "shared" / "supported_languages.json"
with open(_LANGUAGES_JSON_PATH) as f:
    _languages_list = json.load(f)
SUPPORTED_LANGUAGES = {lang["code"]: lang["label"] for lang in _languages_list}

DEFAULT_TARGET_LANGUAGE = "en"

TRANSLATION_MODEL = "gpt-4.1-mini"

# `translate_text` makes a single attempt, so this is the whole wall clock a user waits behind the
# spinner rather than a per-attempt budget. It has to cover a text as long as the 10,000 character
# cap the request serializer enforces, while still returning inside the proxy's request timeout.
TRANSLATION_TIMEOUT_SECONDS = 45.0
