from django.test import SimpleTestCase

from parameterized import parameterized

from products.agent_transcripts.backend.facade.contracts import MAX_TRANSCRIPT_SIZE_BYTES, UploadRejected
from products.agent_transcripts.backend.facade.enums import SecretKind, UploadRejectionReason
from products.agent_transcripts.backend.logic import content

# Built by concatenation so that secret scanners on this repository do not flag the test data.
FAKE_PERSONAL_API_KEY = "phx" + "_" + "0aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uV1wX2yZ3a"
FAKE_PROJECT_TOKEN = "phc" + "_" + "0aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uV1wX2yZ3a"
FAKE_PROJECT_SECRET_KEY = "phs" + "_" + "0aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uV1wX2yZ3a"
FAKE_HEATMAP_SCREENSHOT_SECRET = "phh" + "_" + "0aB1cD2eF3gH4iJ5kL6mN7"
FAKE_OAUTH_ACCESS_TOKEN = "pha" + "_" + "0aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uV1wX2yZ3a"
FAKE_OAUTH_REFRESH_TOKEN = "phr" + "_" + "0aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uV1wX2yZ3a"
FAKE_OPENAI_KEY = "sk" + "-proj-" + "0aB1cD2eF3gH4iJ5kL6mN7oP8"
FAKE_ANTHROPIC_KEY = "sk" + "-ant-api03-" + "0aB1cD2eF3gH4iJ5kL6mN7oP8"
FAKE_AWS_ACCESS_KEY_ID = "AKIA" + "IOSFODNN7EXAMPLE"
FAKE_GITHUB_TOKEN = "ghp" + "_" + "0" * 36
FAKE_GITHUB_FINE_GRAINED_TOKEN = "github" + "_pat_" + "0aB1cD2eF3gH4iJ5kL6mN7oP8"
FAKE_PRIVATE_KEY_HEADER = "-----BEGIN " + "RSA PRIVATE KEY-----"
FAKE_GITLAB_TOKEN = "glpat" + "-" + "0aB1cD2eF3gH4iJ5kL6m"
FAKE_GOOGLE_API_KEY = "AIza" + "0aB1cD2eF3gH4iJ5kL6mN7oP8qR9sT0uV1w"
FAKE_SLACK_TOKEN = "xoxb" + "-" + "000000000000-000000000000-0aB1cD2eF3gH4iJ5kL6mN7oP"


def _transcript(line: str) -> bytes:
    return f'{{"role": "user", "content": "{line}"}}\n'.encode()


class TestCheckContent(SimpleTestCase):
    @parameterized.expand(
        [
            ("too_large", "chat.jsonl", b"a" * (MAX_TRANSCRIPT_SIZE_BYTES + 1), UploadRejectionReason.TOO_LARGE),
            ("empty", "chat.jsonl", b"", UploadRejectionReason.EMPTY),
            ("pdf", "chat.pdf", b"plain text", UploadRejectionReason.UNSUPPORTED_EXTENSION),
            ("no_extension", "chat", b"plain text", UploadRejectionReason.UNSUPPORTED_EXTENSION),
            ("invalid_utf8", "chat.txt", b"\x89PNG\r\n\x1a\n\xff\xfe", UploadRejectionReason.NOT_TEXT),
            ("nul_bytes", "chat.txt", b"text\x00with\x00nul", UploadRejectionReason.NOT_TEXT),
        ]
    )
    def test_rejects_file(self, _name: str, filename: str, data: bytes, reason: UploadRejectionReason) -> None:
        with self.assertRaises(UploadRejected) as raised:
            content.check_content(filename=filename, content=data)

        assert raised.exception.reason == reason

    @parameterized.expand(
        [
            ("posthog_personal_api_key", FAKE_PERSONAL_API_KEY, SecretKind.POSTHOG_PERSONAL_API_KEY),
            ("posthog_project_secret_key", FAKE_PROJECT_SECRET_KEY, SecretKind.POSTHOG_SECRET_KEY),
            ("posthog_heatmap_screenshot_secret", FAKE_HEATMAP_SCREENSHOT_SECRET, SecretKind.POSTHOG_SECRET_KEY),
            ("posthog_oauth_access_token", FAKE_OAUTH_ACCESS_TOKEN, SecretKind.POSTHOG_OAUTH_TOKEN),
            ("posthog_oauth_refresh_token", FAKE_OAUTH_REFRESH_TOKEN, SecretKind.POSTHOG_OAUTH_TOKEN),
            ("openai_key", FAKE_OPENAI_KEY, SecretKind.PROVIDER_API_KEY),
            ("anthropic_key", FAKE_ANTHROPIC_KEY, SecretKind.PROVIDER_API_KEY),
            ("aws_access_key_id", FAKE_AWS_ACCESS_KEY_ID, SecretKind.AWS_ACCESS_KEY_ID),
            ("github_token", FAKE_GITHUB_TOKEN, SecretKind.GITHUB_TOKEN),
            ("github_fine_grained_token", FAKE_GITHUB_FINE_GRAINED_TOKEN, SecretKind.GITHUB_TOKEN),
            ("private_key", FAKE_PRIVATE_KEY_HEADER, SecretKind.PRIVATE_KEY),
            ("gitlab_token", FAKE_GITLAB_TOKEN, SecretKind.GITLAB_TOKEN),
            ("google_api_key", FAKE_GOOGLE_API_KEY, SecretKind.GOOGLE_API_KEY),
            ("slack_token", FAKE_SLACK_TOKEN, SecretKind.SLACK_TOKEN),
        ]
    )
    def test_rejects_secret(self, _name: str, secret: str, kind: SecretKind) -> None:
        with self.assertRaises(UploadRejected) as raised:
            content.check_content(filename="chat.jsonl", content=_transcript(f"my key is {secret} thanks"))

        assert raised.exception.reason == UploadRejectionReason.CONTAINS_SECRET
        assert raised.exception.secret_kind == kind
        assert secret not in str(raised.exception)

    @parameterized.expand(
        [
            ("project_token", f"posthog.init('{FAKE_PROJECT_TOKEN}')"),
            ("prefix_mentioned_in_prose", "personal keys start with phx_ and GitHub tokens with ghp_"),
            (
                "more_prefixes_in_prose",
                "secret keys start with phs_, Slack tokens with xoxb- and GitLab ones with glpat-",
            ),
            ("short_sk_word", "pip install scikit-learn, also known as sk-learn"),
            ("kebab_case_name_after_sk", "the sk-onboarding-checklist-component renders the steps"),
            ("public_key_header", "-----BEGIN " + "PUBLIC KEY-----"),
        ]
    )
    def test_accepts_text_without_a_credential(self, _name: str, line: str) -> None:
        content.check_content(filename="chat.jsonl", content=_transcript(line))


class TestStorageFilename(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain", "chat.jsonl", "chat.jsonl"),
            ("path_traversal", "../../etc/passwd.txt", "passwd.txt"),
            ("windows_path", "C:\\Users\\me\\chat.md", "chat.md"),
            ("unsafe_characters", 'my "chat"\r\n.json', "my_chat.json"),
            ("only_unsafe_characters", "???.txt", "transcript.txt"),
            ("uppercase_extension", "Chat.JSONL", "Chat.jsonl"),
        ]
    )
    def test_storage_filename(self, _name: str, filename: str, expected: str) -> None:
        assert content.storage_filename(filename) == expected
