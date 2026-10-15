from copy import deepcopy

from pydantic import JsonValue
from rest_framework.exceptions import PermissionDenied

from posthog.hogql.restricted_properties import restricted_feature_flag_names


class MCPEventPropertyAccess:
    @staticmethod
    def validate(name: str | None, restricted_names: set[str]) -> None:
        if not restricted_names:
            return
        if name is None:
            raise PermissionDenied("The filter reads a properties object your account cannot fully access.")
        name = name.replace("%2E", ".")
        keys = {key.replace("%2E", ".") for key in restricted_names}
        if any(name == key or name.startswith(key + ".") or key.startswith(name + ".") for key in keys):
            raise PermissionDenied("The filter uses a property your account cannot read.")
        if restricted_feature_flag_names(keys) and name.split(".")[0] in {"$active_feature_flags", "$feature_flags"}:
            raise PermissionDenied("The filter reads feature flags your account cannot fully access.")

    @classmethod
    def _remove_path(cls, value: JsonValue, path: list[str]) -> None:
        if isinstance(value, list):
            for item in value:
                cls._remove_path(item, path)
        elif isinstance(value, dict):
            value.pop(".".join(path), None)
            value.pop("%2E".join(path), None)
            if len(path) > 1 and path[0] in value:
                cls._remove_path(value[path[0]], path[1:])

    @classmethod
    def redact(cls, properties: dict[str, JsonValue], restricted_names: set[str]) -> dict[str, JsonValue]:
        result = deepcopy(properties)
        for key in restricted_names:
            cls._remove_path(result, key.replace("%2E", ".").split("."))
        flags = set(restricted_feature_flag_names(restricted_names))
        if flags:
            active = result.get("$active_feature_flags")
            if isinstance(active, list):
                result["$active_feature_flags"] = [
                    flag for flag in active if isinstance(flag, str) and flag not in flags
                ]
            else:
                result.pop("$active_feature_flags", None)
            values = result.get("$feature_flags")
            if isinstance(values, dict):
                result["$feature_flags"] = {key: value for key, value in values.items() if key not in flags}
            else:
                result.pop("$feature_flags", None)
        return result
