# Make tasks ready for celery autoimport
import posthog.tasks.calculate_action
import posthog.tasks.calculate_cohort
import posthog.tasks.email
import posthog.tasks.process_event
import posthog.tasks.session_recording_retention
import posthog.tasks.status_report
import posthog.tasks.update_cache
import posthog.tasks.webhooks
