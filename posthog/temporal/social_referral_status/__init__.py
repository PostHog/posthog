from posthog.temporal.social_referral_status.activities import (
    referral_status_list_pending_ingestion_activity,
    referral_status_process_single_ingestion_activity,
    referral_status_record_ingestion_check_failure_activity,
)
from posthog.temporal.social_referral_status.workflow import SocialReferralStatusWorkflow

WORKFLOWS = [SocialReferralStatusWorkflow]

ACTIVITIES = [
    referral_status_list_pending_ingestion_activity,
    referral_status_process_single_ingestion_activity,
    referral_status_record_ingestion_check_failure_activity,
]
