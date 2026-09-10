import json


def get_workflow_input_size_estimates(inputs: object) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for field_name in ("message", "contextual_tools", "billing_context", "resume_payload"):
        value = getattr(inputs, field_name, None)
        if value is None:
            continue
        try:
            sizes[field_name] = len(json.dumps(value, default=str, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError, RecursionError):
            continue
    return sizes
