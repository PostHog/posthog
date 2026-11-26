"""
Exported enums for agent_transcripts.

No Django imports: these back model and serializer choices through LabeledStrEnum.
"""

from posthog.enums import LabeledStrEnum


class SubmissionStatus(LabeledStrEnum):
    PENDING_UPLOAD = "pending_upload", "Pending upload"
    SUBMITTED = "submitted", "Submitted"
    CHANGES_REQUESTED = "changes_requested", "Changes requested"
    APPROVED = "approved", "Approved"
    DECLINED = "declined", "Declined"


class TranscriptAgent(LabeledStrEnum):
    CLAUDE_CODE = "claude_code", "Claude Code"
    CODEX = "codex", "Codex"
    CURSOR = "cursor", "Cursor"
    CLAUDE_APP = "claude_app", "Claude app"
    CHATGPT = "chatgpt", "ChatGPT"
    OTHER = "other", "Other"


class SubmissionAction(LabeledStrEnum):
    START_UPLOAD = "start_upload", "Start upload"
    COMPLETE_UPLOAD = "complete_upload", "Complete upload"
    REVIEW = "review", "Review"


class UploadRejectionReason(LabeledStrEnum):
    NOT_UPLOADED = "not_uploaded", "Not uploaded"
    EMPTY = "empty", "Empty"
    TOO_LARGE = "too_large", "Too large"
    UNSUPPORTED_EXTENSION = "unsupported_extension", "Unsupported extension"
    NOT_TEXT = "not_text", "Not text"
    CONTAINS_SECRET = "contains_secret", "Contains secret"


class SecretKind(LabeledStrEnum):
    POSTHOG_PERSONAL_API_KEY = "posthog_personal_api_key", "PostHog personal API key"
    POSTHOG_SECRET_KEY = "posthog_secret_key", "PostHog secret key"
    POSTHOG_OAUTH_TOKEN = "posthog_oauth_token", "PostHog OAuth token"
    PROVIDER_API_KEY = "provider_api_key", "AI provider API key"
    AWS_ACCESS_KEY_ID = "aws_access_key_id", "AWS access key ID"
    GITHUB_TOKEN = "github_token", "GitHub token"
    GITLAB_TOKEN = "gitlab_token", "GitLab token"
    GOOGLE_API_KEY = "google_api_key", "Google API key"
    SLACK_TOKEN = "slack_token", "Slack token"
    PRIVATE_KEY = "private_key", "Private key"
