from rest_framework import serializers

from ...facade import api


class TracePageRequestSerializer(serializers.Serializer):
    trace_ids = serializers.ListField(
        child=serializers.CharField(trim_whitespace=False),
        min_length=1,
        max_length=api.TRACE_LIST_MAX_LIMIT,
        help_text=f"The IDs of the traces on a page of the list, from 1 to {api.TRACE_LIST_MAX_LIMIT}. Items come back "
        "in this order, once per ID.",
    )
