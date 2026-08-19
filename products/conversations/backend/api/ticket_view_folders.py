from typing import Any

from rest_framework import serializers

from posthog.models.file_system.file_system import join_path, split_path

MAX_FOLDER_LENGTH = 1000
MAX_FOLDER_DEPTH = 10
MAX_FOLDER_SEGMENT_LENGTH = 100


def normalize_folder(value: Any) -> str:
    """Reduce a caller-supplied folder path to its canonical stored form: "/a//b/" -> "a/b".

    Idempotent, because the frontend round-trips whatever the API handed it. Raises
    ValidationError so both the serializer field and the move_folder action surface a 400.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise serializers.ValidationError("Folder must be a string.")

    # split_path drops empty segments, so stray leading, trailing, and doubled slashes
    # normalize away instead of erroring.
    segments = [segment.strip() for segment in split_path(value)]
    segments = [segment for segment in segments if segment]

    for segment in segments:
        if any(ord(character) < 0x20 or ord(character) == 0x7F for character in segment):
            raise serializers.ValidationError("Folder names can't contain line breaks or control characters.")
        if len(segment) > MAX_FOLDER_SEGMENT_LENGTH:
            raise serializers.ValidationError(
                f"Folder names can't be longer than {MAX_FOLDER_SEGMENT_LENGTH} characters."
            )

    if len(segments) > MAX_FOLDER_DEPTH:
        raise serializers.ValidationError(f"Folders can't be nested more than {MAX_FOLDER_DEPTH} levels deep.")

    normalized = join_path(segments)
    if len(normalized) > MAX_FOLDER_LENGTH:
        raise serializers.ValidationError(f"Folder path can't be longer than {MAX_FOLDER_LENGTH} characters.")
    return normalized


def is_folder_under(folder: str, ancestor: str) -> bool:
    """True for `ancestor` itself and anything beneath it. The root ("") contains everything.

    Compares whole segments, so a sibling that merely shares a name prefix does not match.
    """
    ancestor_segments = split_path(ancestor)
    return split_path(folder)[: len(ancestor_segments)] == ancestor_segments


def reparent_folder(folder: str, from_folder: str, to_folder: str) -> str:
    """Rewrite `folder` as if `from_folder` had moved to `to_folder`."""
    suffix = split_path(folder)[len(split_path(from_folder)) :]
    return join_path(split_path(to_folder) + suffix)
