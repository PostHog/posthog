from rest_framework import serializers


class AccountAutomationSerializer(serializers.Serializer):
    workflow_id = serializers.CharField(help_text="ID of the workflow the caller can read.")
    workflow_name = serializers.CharField(help_text="Name of the workflow.")
    invocation_id = serializers.CharField(help_text="ID of this execution, including repeated workflow runs.")
    status = serializers.CharField(help_text="Run status: running, succeeded, failed, or canceled.")
    triggered_at = serializers.DateTimeField(help_text="Original trigger or scheduling time.")
    last_completed_step_at = serializers.DateTimeField(
        allow_null=True, help_text="Last successfully completed step time, or null when evidence is unavailable."
    )
    last_completed_step_name = serializers.CharField(
        allow_null=True, help_text="Current name of the last completed step, or null when unavailable."
    )
    expected_resume_at = serializers.DateTimeField(
        allow_null=True, help_text="Future pause time from retained logs, or null. This does not guarantee an action."
    )
