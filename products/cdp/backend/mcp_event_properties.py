from copy import deepcopy
from typing import TYPE_CHECKING

from pydantic import JsonValue
from rest_framework.exceptions import PermissionDenied

from posthog.hogql.restricted_properties import restricted_feature_flag_names

from posthog.constants import GROUP_TYPES_LIMIT
from posthog.models.group_type_mapping import get_group_types_for_project

if TYPE_CHECKING:
    from posthog.models import Team


class MCPEventPropertyAccess:
    @staticmethod
    def _paths_overlap(name: str, key: str) -> bool:
        return name == key or name.startswith(key + ".") or key.startswith(name + ".")

    @classmethod
    def with_group_aliases(cls, restricted_names: set[str], *, team: "Team") -> set[str]:
        keys = {key.replace("%2E", ".") for key in restricted_names}
        indexed = {f"$group_{index}" for index in range(GROUP_TYPES_LIMIT)}
        if not any(cls._paths_overlap(key, "$groups") or key in indexed for key in keys):
            return keys
        group_types = {
            mapping["group_type_index"]: mapping["group_type"]
            for mapping in get_group_types_for_project(team.project_id)
        }
        expanded = keys.copy()
        for index in range(GROUP_TYPES_LIMIT):
            alias = f"$group_{index}"
            group_type = group_types.get(index)
            canonical = (f"$groups.{group_type}" if group_type is not None else "$groups").replace("%2E", ".")
            if any(cls._paths_overlap(key, canonical) for key in keys):
                expanded.add(alias)
            if any(cls._paths_overlap(key, alias) for key in keys):
                expanded.update({alias, canonical})
        return expanded

    @classmethod
    def validate(cls, name: str | None, restricted_names: set[str]) -> None:
        if not restricted_names:
            return
        if name is None:
            raise PermissionDenied("The filter reads a properties object your account cannot fully access.")
        name = name.replace("%2E", ".")
        keys = {key.replace("%2E", ".") for key in restricted_names}
        if "$feature_flags" in keys and (
            name.startswith("$feature/") or name.split(".")[0] in {"$active_feature_flags", "$feature_flags"}
        ):
            raise PermissionDenied("The filter reads feature flags your account cannot fully access.")
        if any(cls._paths_overlap(name, key) for key in keys):
            raise PermissionDenied("The filter uses a property your account cannot read.")
        if restricted_feature_flag_names(keys) and name.split(".")[0] in {"$active_feature_flags", "$feature_flags"}:
            raise PermissionDenied("The filter reads feature flags your account cannot fully access.")

    @classmethod
    def _remove_path(cls, value: JsonValue, path: list[str]) -> None:
        if isinstance(value, list):
            for item in value:
                cls._remove_path(item, path)
        elif isinstance(value, dict):
            target = ".".join(path)
            for key in list(value):
                normalized = key.replace("%2E", ".")
                if normalized == target or normalized.startswith(target + "."):
                    value.pop(key)
                elif target.startswith(normalized + "."):
                    cls._remove_path(value[key], target[len(normalized) + 1 :].split("."))

    @classmethod
    def redact(cls, properties: dict[str, JsonValue], restricted_names: set[str]) -> dict[str, JsonValue]:
        result = deepcopy(properties)
        for key in restricted_names:
            cls._remove_path(result, key.replace("%2E", ".").split("."))
        if "$feature_flags" in restricted_names:
            for key in list(result):
                if key.startswith("$feature/") or key == "$active_feature_flags":
                    result.pop(key)
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
