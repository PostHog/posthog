from typing import Any
from urllib.parse import unquote_plus

_CREDENTIAL_QUERY_PARAMS = frozenset({"personal_api_key", "token", "access_token", "api_key"})
_REDACTED = "<redacted>"


def redact_credential_query_params(request_line: str) -> str:
    path, separator, query = request_line.partition("?")
    if not separator:
        return request_line
    params = query.split("&")
    for index, param in enumerate(params):
        name, has_value, _ = param.partition("=")
        if has_value and unquote_plus(name).lower() in _CREDENTIAL_QUERY_PARAMS:
            params[index] = f"{name}={_REDACTED}"
    return f"{path}?{'&'.join(params)}"


def redact_credential_query_params_in_properties(properties: dict[str, Any]) -> dict[str, Any]:
    current_url = properties.get("$current_url")
    if isinstance(current_url, str):
        properties["$current_url"] = redact_credential_query_params(current_url)
    return properties
