ANTHROPIC_TO_BEDROCK_MODEL_MAP: dict[str, str] = {
    "claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-6",
    "claude-sonnet-4-5": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-opus-4-5-20251101": "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "claude-opus-4-6": "us.anthropic.claude-opus-4-6",
    "claude-haiku-4-5": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
}


def to_bedrock_model_id(anthropic_model: str) -> str:
    bedrock_model = ANTHROPIC_TO_BEDROCK_MODEL_MAP.get(anthropic_model)
    if not bedrock_model:
        raise ValueError(f"No Bedrock model mapping for: {anthropic_model}")
    return bedrock_model
