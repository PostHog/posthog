from rest_framework import serializers


class AdvancedActivityLogFiltersSerializer(serializers.Serializer):
    start_date = serializers.DateTimeField(required=False)
    end_date = serializers.DateTimeField(required=False)
    users = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    scopes = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    activities = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    search_text = serializers.CharField(required=False, allow_blank=True)
    detail_filters = serializers.JSONField(required=False, default=dict)
    hogql_filter = serializers.CharField(required=False, allow_blank=True)
