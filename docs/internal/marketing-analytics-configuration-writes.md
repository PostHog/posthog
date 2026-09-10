# Marketing configuration writes

Marketing settings PATCH requests send only the setting being changed. Updating filters or attribution settings must not resend an old conversion-goal list.

The configuration serializer refreshes the marketing configuration under a row lock before applying a partial update. This preserves fields changed by concurrent goal operations and source mappings. It does not lock the parent project row.

Explicit conversion-goal list updates still replace the list. This change does not merge simultaneous edits to the same goal list or change the API schema.

Validation covers a stale settings instance saved after goal creation and a frontend filter update that omits goals from its payload.
