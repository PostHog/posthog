"""DRF serializers for the agent-memory HTTP surface.

Output serializers wrap the frozen contracts from `facade/contracts.py` via
`DataclassSerializer`; field types are auto-derived, so we only add `help_text`.
Input serializers are plain serializers validating untrusted JSON at the wire.
"""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade import contracts
from ..logic import MAX_FILE_BYTES, MAX_PATH_LENGTH


class MemoryFileSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.MemoryFile

    path = serializers.CharField(
        help_text="Relative path of the file within the team's memory tree, e.g. 'project.md'."
    )
    content = serializers.CharField(help_text="Full markdown body of the file.")
    version = serializers.IntegerField(
        help_text="Monotonic version of the file. Pass this back as `expected_version` on the next write to detect "
        "conflicting concurrent edits (compare-and-set)."
    )
    updated_by_id = serializers.IntegerField(
        allow_null=True, help_text="ID of the user who last wrote the file, or null if written by an agent run."
    )
    updated_by_run = serializers.CharField(
        allow_null=True, help_text="Identifier of the agent run that last wrote the file, or null."
    )


class MemoryFileSummarySerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.MemoryFileSummary

    path = serializers.CharField(help_text="Relative path of the file within the team's memory tree.")
    version = serializers.IntegerField(help_text="Monotonic version of the file.")
    size_bytes = serializers.IntegerField(help_text="UTF-8 byte length of the file's content.")
    updated_by_run = serializers.CharField(
        allow_null=True, help_text="Identifier of the agent run that last wrote the file, or null."
    )


class MemoryWriteInputSerializer(serializers.Serializer):
    path = serializers.CharField(
        max_length=MAX_PATH_LENGTH,
        help_text="Relative path of the file to write, e.g. 'project.md' or 'users/jane-doe.md'. Must end in '.md', "
        "may not contain '..' or absolute segments.",
    )
    content = serializers.CharField(
        allow_blank=True,
        trim_whitespace=False,
        max_length=MAX_FILE_BYTES,
        help_text="Full markdown body to store. Replaces the file's content entirely — prefer the append endpoint "
        "to add a section without clobbering concurrent edits.",
    )
    expected_version = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Compare-and-set token. Omit (or null) to create a new file; pass the version you last read to "
        "update an existing one. A mismatch returns 409 — re-read and merge before retrying.",
    )


class MemoryAppendInputSerializer(serializers.Serializer):
    path = serializers.CharField(
        max_length=MAX_PATH_LENGTH,
        help_text="Relative path of the file to append to, e.g. 'project.md'. Created if it does not exist.",
    )
    heading = serializers.CharField(
        max_length=500,
        help_text="Section title (without leading '#'). If a section with this title already exists, its body is "
        "replaced; otherwise a new '## {heading}' section is appended.",
    )
    body = serializers.CharField(
        allow_blank=True,
        trim_whitespace=False,
        max_length=MAX_FILE_BYTES,
        help_text="Markdown body for the section. Never clobbers other sections of the file.",
    )


class MemoryConflictResponseSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Human-readable conflict description.")
    code = serializers.CharField(help_text="Stable error code; 'version_conflict' for compare-and-set failures.")
    path = serializers.CharField(help_text="The path that conflicted.")
    expected_version = serializers.IntegerField(help_text="The version the writer supplied.")
    actual_version = serializers.IntegerField(help_text="The version currently stored — re-read at this version.")


class MemoryDeleteResponseSerializer(serializers.Serializer):
    deleted = serializers.BooleanField(help_text="Whether a file was deleted. False means there was nothing to delete.")
