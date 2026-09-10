import os


def get_ai_research_replay_env(name: str, default: str = "") -> str:
    legacy_name = name.replace("AI_RESEARCH_REPLAY_", "SESSION_RECORDING_ML_", 1)
    return os.environ.get(name, os.environ.get(legacy_name, default))
