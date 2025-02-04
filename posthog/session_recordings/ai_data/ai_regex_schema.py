# https://platform.openai.com/docs/guides/structured-outputs?lang=javascript
AI_REGEX_SCHEMA = {
    "name": "simple_response",
    "schema": {
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "enum": ["success", "error"],
                "description": "Indicates the result of the operation.",
            },
            "data": {
                "type": "object",
                "description": "Contains additional data related to the response.",
                "properties": {
                    "output": {"type": "string", "description": "The output information from the response."}
                },
                "required": ["output"],
                "additionalProperties": False,
            },
        },
        "required": ["result", "data"],
        "additionalProperties": False,
    },
    "strict": True,
}
