# Endpoint materialization lifecycle

Endpoint versions can pause unused materialization after 30 days.
The cleanup task considers API-key calls only; Playground and other session-authenticated calls do not count as usage.
A version is eligible when its materialization is at least 30 days old and has run within the past 24 hours.
Versions that have never received an API-key call are eligible once the version is also 30 days old.
Superseded versions with no execution timestamp remain eligible.

Pausing reverts and soft-deletes the backing saved query and records `materialization_hibernated_at` on the endpoint version.
Members who can view the endpoint receive an in-app notification when notifications are enabled.
The configuration panel explains the pause and offers **Resume materialization** through the existing toggle and save flow.
There is no hibernation email or wake notification.

The next API-key execution claims the pause marker and queues a single background enable attempt.
The request executes inline while the background job recreates materialization.
Calls continue inline until fresh materialized results exist.
Inline execution can take longer or time out, uses the inline rate budget, and applies inline variable requirements.
The endpoint remains available in its OpenAPI specification; variable and refresh options follow its current serving configuration.

The wake job checks that the endpoint and version are active, that no saved query has been attached, and that the query can still be materialized.
A version edit after dispatch cancels the queued wake.
Failures leave the endpoint inline with the marker cleared, so subsequent requests do not repeatedly retry an unsuccessful enable.
Users can retry with **Resume materialization** while paused, or **Enable materialization** after a failed wake.
Explicitly disabling materialization or deactivating a version or endpoint clears its pause marker.

Enabling materialization records a system activity attributed to PostHog when no request user exists.
Both pause and enable invalidate the serving-state cache used by throttling.
The existing `ENDPOINT_MATERIALIZATION_EVENT_TOTAL` counter records `action="hibernate"` and `action="wake"`, with success or error status.
The scheduled Celery task retains its existing `deactivate_stale_materializations` name for compatibility.
