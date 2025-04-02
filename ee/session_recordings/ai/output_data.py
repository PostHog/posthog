from rest_framework import serializers
from openai.types.chat.chat_completion import ChatCompletion
import yaml


class EventTagSerializer(serializers.Serializer):
    where = serializers.ListField(child=serializers.CharField(min_length=1, max_length=256), allow_empty=False)
    what = serializers.ListField(child=serializers.CharField(min_length=1, max_length=256), allow_empty=False)


class KeyEventSerializer(serializers.Serializer):
    event_id = serializers.CharField(min_length=1, max_length=128)
    description = serializers.CharField(min_length=1, max_length=1024)
    error = serializers.BooleanField()
    tags = EventTagSerializer()


class SessionSummarySerializer(serializers.Serializer):
    summary = serializers.CharField(min_length=1, max_length=2048)
    key_events = serializers.ListField(child=KeyEventSerializer(), allow_empty=False)


def load_session_summary_from_llm_content(llm_content: ChatCompletion, session_id: str) -> SessionSummarySerializer:
    raw_content: str = llm_content.choices[0].message.content
    if not raw_content:
        raise ValueError(f"No LLM content found when summarizing session_id {session_id}: {llm_content}")
    try:
        # Strip the first and the last line of the content to load the YAML data only into JSON
        # TODO Work on a more robust solution
        json_content: dict = yaml.safe_load(raw_content.strip("```yaml\n").strip("```").strip())  # noqa: B005
    except Exception as e:
        raise ValueError(f"Error loading YAML content into JSON when summarizing session_id {session_id}: {e}")
    # Validate the LLM output against the schema
    session_summary = SessionSummarySerializer(data=json_content)
    if not session_summary.is_valid():
        raise ValueError(
            f"Error validating LLM output against the schema when summarizing session_id {session_id}: {session_summary.errors}"
        )
    # TODO Enrich the content with the URLs/timestamps/window ids/etc. based on the event_id
    return session_summary
