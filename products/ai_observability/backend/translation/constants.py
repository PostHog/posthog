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
