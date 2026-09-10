# Legacy AI context payloads

Legacy AI insight and dashboard attachments contain query definitions, not cached query responses.
The frontend removes `response` from query nodes, including nested sources and series.
It does not change the original query or remove user-supplied values named `response`.
Dashboard tiles use the same insight conversion.

If an AI workflow fails to start, the existing `Error starting workflow` log includes
`workflow_input_estimated_bytes`. This contains JSON byte estimates for `message`,
`contextual_tools`, `billing_context`, and `resume_payload`, when present.
These estimates help identify large input fields. They are not exact Temporal wire sizes.
The size diagnostic does not include field contents. Fields that cannot be serialized are omitted.

Removing cached responses does not impose a size limit on query definitions or other context.
If a request still exceeds the workflow payload limit, use the size estimates to identify the input
that needs to be reduced or stored separately and passed by reference.
