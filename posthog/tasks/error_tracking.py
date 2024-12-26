from sentry_sdk import capture_exception
from posthog.models.error_tracking.error_tracking import ErrorTrackingIssue
from posthog.redis import get_client
from django.db.models import F


def populate_error_tracking_issue_metrics():
    client = get_client()
    keys = client.scan_iter(match="issue_metadata:*", count=20)
    for key in keys:
        # check key is valid
        parts = key.split(":")
        if len(parts) != 3:
            continue

        team_id = parts[1]
        issue_id = parts[2]

        # Fetch data associated with the key
        data = client.hgetall(key)
        last_seen = data.get(b"last_seen")
        occurrences = data.get(b"occurrences")

        try:
            # update the issue and reset redis key
            ErrorTrackingIssue.objects.filter(team=team_id, id=issue_id).update(
                last_seen=last_seen, occurrences=F("occurrences") + occurrences
            )
            # :TRICKY: Resetting the redis key here is prone to race conditions,
            # but given we sync later and the data here is not critical, just an estimate for sorting,
            # I'm skipping locking and letting this be.
            client.delete(key)
        except Exception as error:
            capture_exception(error)
            continue
