"""Shared GitHub callback validation helpers."""

from __future__ import annotations

import re

from rest_framework.exceptions import ValidationError

GITHUB_INSTALLATION_ID_PATTERN = re.compile(r"\d{1,20}")


def is_valid_github_installation_id(installation_id: object | None) -> bool:
    if installation_id is None:
        return False
    return bool(GITHUB_INSTALLATION_ID_PATTERN.fullmatch(str(installation_id)))


def validation_error_code(exc: ValidationError) -> str | None:
    codes = exc.get_codes()
    if isinstance(codes, list) and codes:
        return str(codes[0])
    if isinstance(codes, dict) and codes:
        first = next(iter(codes.values()))
        if isinstance(first, list) and first:
            return str(first[0])
        return str(first)
    if isinstance(codes, str):
        return codes
    return None
