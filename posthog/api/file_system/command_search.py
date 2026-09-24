from __future__ import annotations

from rest_framework import serializers

from posthog.helpers.command_search import MAX_COMMANDS, CommandCandidate


class CommandCandidateSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=200, help_text="ID of an available command in the palette.")
    name = serializers.CharField(max_length=200, help_text="Display name of the command.")
    description = serializers.CharField(max_length=400, allow_blank=True, help_text="Category and search keywords.")


class CommandSearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=200, help_text="Search text, including unfinished words.")
    commands: serializers.ListSerializer[CommandCandidate] = serializers.ListSerializer(
        child=CommandCandidateSerializer(), max_length=MAX_COMMANDS, help_text="Available palette commands."
    )


class CommandSearchResultSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable result ID.")
    name = serializers.CharField(help_text="Display name.")
    description = serializers.CharField(help_text="Search context.")
    href = serializers.CharField(allow_blank=True, help_text="File navigation URL; empty for commands.")
    type = serializers.CharField(help_text="File type, or command.")
    command_id = serializers.CharField(allow_blank=True, help_text="Original command ID; empty for files.")


class CommandSearchResponseSerializer(serializers.Serializer):
    results = CommandSearchResultSerializer(many=True, help_text="Complete results in relevance order.")
