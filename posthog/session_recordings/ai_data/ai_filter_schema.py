# https://platform.openai.com/docs/guides/structured-outputs?lang=javascript
AI_FILTER_SCHEMA = {
    "name": "response_schema",
    "schema": {
        "type": "object",
        "properties": {
            "result": {"type": "string", "enum": ["question", "filter"]},
            "data": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "filter_group": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["AND", "OR"]},
                            "values": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "type": {"type": "string", "enum": ["AND", "OR"]},
                                        "values": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "key": {"type": "string"},
                                                    "type": {
                                                        "type": "string",
                                                        "enum": [
                                                            "meta",
                                                            "event",
                                                            "person",
                                                            "element",
                                                            "session",
                                                            "cohort",
                                                            "recording",
                                                            "log_entry",
                                                            "group",
                                                            "hogql",
                                                            "data_warehouse",
                                                            "data_warehouse_person_property",
                                                        ],
                                                    },
                                                    "value": {"type": "array", "items": {"type": "string"}},
                                                    "operator": {
                                                        "type": "string",
                                                        "enum": [
                                                            "exact",
                                                            "is_not",
                                                            "icontains",
                                                            "not_icontains",
                                                            "regex",
                                                            "not_regex",
                                                            "gt",
                                                            "gte",
                                                            "lt",
                                                            "lte",
                                                            "is_set",
                                                            "is_not_set",
                                                            "is_date_exact",
                                                            "is_date_before",
                                                            "is_date_after",
                                                            "between",
                                                            "not_between",
                                                            "min",
                                                            "max",
                                                            "in",
                                                            "not_in",
                                                        ],
                                                    },
                                                },
                                                "required": ["key", "type", "value", "operator"],
                                                "additionalProperties": False,
                                            },
                                        },
                                    },
                                    "required": ["type", "values"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["type", "values"],
                        "additionalProperties": False,
                    },
                },
                "required": ["question", "date_from", "date_to", "filter_group"],
                "additionalProperties": False,
            },
        },
        "required": ["result", "data"],
        "additionalProperties": False,
    },
    "strict": True,
}
