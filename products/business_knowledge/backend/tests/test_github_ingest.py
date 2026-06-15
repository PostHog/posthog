"""
Tests for GitHub repository source ingestion.

Scope:
- URL parsing (various github.com URL formats, .git suffix, /tree/ref/subdir).
- Tarball extraction with glob filtering.
- Ingest/refresh flows via logic._ingest_github_source / _refresh_github_source.
- Serializer validation for github_repo crawl mode.
"""

import io
import tarfile

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from products.business_knowledge.backend import github
from products.business_knowledge.backend.api.serializers import CreateCrawlSourceSerializer, UpdateUrlSourceSerializer
from products.business_knowledge.backend.discover import CrawlConfig
from products.business_knowledge.backend.logic import ingest_source, refresh_source
from products.business_knowledge.backend.models import (
    CrawlMode,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    SourceStatus,
    SourceType,
)


class TestParseRepoUrl(BaseTest):
    @parameterized.expand(
        [
            ("https://github.com/owner/repo", "owner", "repo", None, None),
            ("https://github.com/owner/repo.git", "owner", "repo", None, None),
            ("https://github.com/owner/repo/", "owner", "repo", None, None),
            ("http://github.com/owner/repo", "owner", "repo", None, None),
            ("https://github.com/PostHog/posthog-js", "PostHog", "posthog-js", None, None),
            ("https://github.com/owner/repo/tree/main", "owner", "repo", "main", None),
            ("https://github.com/owner/repo/tree/v1.2.3", "owner", "repo", "v1.2.3", None),
            ("https://github.com/owner/repo/tree/main/docs", "owner", "repo", "main", "docs"),
            ("https://github.com/owner/repo/tree/main/path/to/subdir", "owner", "repo", "main", "path/to/subdir"),
        ]
    )
    def test_parses_valid_urls(
        self, url: str, expected_owner: str, expected_repo: str, expected_ref: str | None, expected_subdir: str | None
    ) -> None:
        result = github.parse_repo_url(url)
        assert result.owner == expected_owner
        assert result.repo == expected_repo
        assert result.ref == expected_ref
        assert result.subdir == expected_subdir

    @parameterized.expand(
        [
            ("https://gitlab.com/owner/repo",),
            ("https://bitbucket.org/owner/repo",),
            ("https://github.com/",),
            ("https://github.com/owner",),
            ("not-a-url",),
            ("ftp://github.com/owner/repo",),
        ]
    )
    def test_rejects_invalid_urls(self, url: str) -> None:
        with self.assertRaises(github.GithubError):
            github.parse_repo_url(url)


def _make_tarball(files: dict[str, str], prefix: str = "repo-abc123") -> bytes:
    """Create an in-memory gzipped tarball with the given files."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path, content in files.items():
            full_path = f"{prefix}/{path}"
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=full_path)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestFetchRepoFiles(BaseTest):
    def test_extracts_matching_files(self) -> None:
        tarball = _make_tarball(
            {
                "README.md": "# Hello",
                "docs/guide.md": "## Guide",
                "src/main.py": "print('hello')",
                "CHANGELOG.txt": "v1.0",
            }
        )

        config = CrawlConfig(include_globs=("*.md", "*.txt"), exclude_globs=(), max_pages=100)

        with patch.object(github, "fetch_stream") as mock_stream:
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            outcomes = github.fetch_repo_files("owner", "repo", "main", config=config)

        assert len(outcomes) == 3
        paths = {o.title for o in outcomes}
        assert paths == {"README.md", "docs/guide.md", "CHANGELOG.txt"}
        for o in outcomes:
            assert o.status == "ok"
            assert o.url.startswith("https://github.com/owner/repo/blob/main/")

    def test_applies_exclude_globs(self) -> None:
        tarball = _make_tarball(
            {
                "README.md": "# Hello",
                "docs/guide.md": "## Guide",
                "docs/private/secret.md": "secret stuff",
            }
        )

        config = CrawlConfig(include_globs=("*.md",), exclude_globs=("docs/private/*",), max_pages=100)

        with patch.object(github, "fetch_stream") as mock_stream:
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            outcomes = github.fetch_repo_files("owner", "repo", "main", config=config)

        paths = {o.title for o in outcomes}
        assert "docs/private/secret.md" not in paths
        assert "README.md" in paths
        assert "docs/guide.md" in paths

    def test_respects_max_pages(self) -> None:
        tarball = _make_tarball({f"file{i}.md": f"content {i}" for i in range(20)})
        config = CrawlConfig(include_globs=("*.md",), exclude_globs=(), max_pages=5)

        with patch.object(github, "fetch_stream") as mock_stream:
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            outcomes = github.fetch_repo_files("owner", "repo", "main", config=config)

        assert len(outcomes) == 5

    def test_skips_binary_files(self) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            txt_data = b"hello"
            txt_info = tarfile.TarInfo(name="repo-abc/readme.txt")
            txt_info.size = len(txt_data)
            tf.addfile(txt_info, io.BytesIO(txt_data))
            bin_data = b"\x00\x01\x02\xff\xfe"
            bin_info = tarfile.TarInfo(name="repo-abc/binary.txt")
            bin_info.size = len(bin_data)
            tf.addfile(bin_info, io.BytesIO(bin_data))
        tarball = buf.getvalue()

        config = CrawlConfig(include_globs=("*.txt",), exclude_globs=(), max_pages=100)

        with patch.object(github, "fetch_stream") as mock_stream:
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            outcomes = github.fetch_repo_files("owner", "repo", "main", config=config)

        assert len(outcomes) == 1
        assert outcomes[0].title == "readme.txt"

    def test_respects_subdir(self) -> None:
        tarball = _make_tarball(
            {
                "README.md": "# Root",
                "docs/guide.md": "## Guide",
                "docs/api/ref.md": "## API Ref",
                "src/code.py": "code",
            }
        )

        config = CrawlConfig(include_globs=("*.md",), exclude_globs=(), max_pages=100)

        with patch.object(github, "fetch_stream") as mock_stream:
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            outcomes = github.fetch_repo_files("owner", "repo", "main", config=config, subdir="docs")

        paths = {o.title for o in outcomes}
        assert paths == {"guide.md", "api/ref.md"}

    def test_skips_oversized_matching_file(self) -> None:
        tarball = _make_tarball(
            {
                "small.md": "tiny",
                "huge.md": "x" * 5000,
            }
        )
        config = CrawlConfig(include_globs=("*.md",), exclude_globs=(), max_pages=100)

        with (
            patch.object(github, "GITHUB_MAX_FILE_BYTES", 100),
            patch.object(github, "fetch_stream") as mock_stream,
        ):
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            outcomes = github.fetch_repo_files("owner", "repo", "main", config=config)

        # Oversized file is skipped, the crawl continues, the small one survives.
        assert {o.title for o in outcomes} == {"small.md"}

    def test_decompressed_ceiling_counts_skipped_members(self) -> None:
        # Large NON-matching members (skipped at the glob step) must still count
        # toward the global decompressed ceiling — tarfile decompresses their
        # bytes to advance the stream. This is the zip-bomb circuit-breaker.
        tarball = _make_tarball(
            {
                "README.md": "# Hello",
                "blob1.bin": "x" * 4000,
                "blob2.bin": "y" * 4000,
            }
        )
        config = CrawlConfig(include_globs=("*.md",), exclude_globs=(), max_pages=100)

        with (
            patch.object(github, "GITHUB_MAX_DECOMPRESSED_BYTES", 5000),
            patch.object(github, "fetch_stream") as mock_stream,
        ):
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            with self.assertRaises(github.GithubError):
                github.fetch_repo_files("owner", "repo", "main", config=config)

    def test_member_count_cap(self) -> None:
        tarball = _make_tarball({f"file{i}.md": "x" for i in range(20)})
        config = CrawlConfig(include_globs=("*.md",), exclude_globs=(), max_pages=100)

        with (
            patch.object(github, "GITHUB_MAX_MEMBERS", 5),
            patch.object(github, "fetch_stream") as mock_stream,
        ):
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            with self.assertRaises(github.GithubError):
                github.fetch_repo_files("owner", "repo", "main", config=config)

    def test_rejects_path_traversal_members(self) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            good = b"# Good"
            good_info = tarfile.TarInfo(name="repo-abc/README.md")
            good_info.size = len(good)
            tf.addfile(good_info, io.BytesIO(good))
            evil = b"pwned"
            evil_info = tarfile.TarInfo(name="repo-abc/../../etc/evil.md")
            evil_info.size = len(evil)
            tf.addfile(evil_info, io.BytesIO(evil))
        tarball = buf.getvalue()

        config = CrawlConfig(include_globs=("*.md",), exclude_globs=(), max_pages=100)

        with patch.object(github, "fetch_stream") as mock_stream:
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            outcomes = github.fetch_repo_files("owner", "repo", "main", config=config)

        # Traversal member is dropped; only the in-root file survives.
        assert {o.title for o in outcomes} == {"README.md"}


class TestGithubIngestSource(BaseTest):
    def test_ingest_creates_documents_and_chunks(self) -> None:
        tarball = _make_tarball(
            {
                "README.md": "# Project\n\nThis is a project.",
                "docs/guide.md": "# Guide\n\nHow to use this project.",
            }
        )

        source = KnowledgeSource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name="Test Repo",
            source_type=SourceType.URL,
            status=SourceStatus.PROCESSING,
            source_url="https://github.com/owner/repo",
            crawl_mode=CrawlMode.GITHUB_REPO,
            crawl_config={"include_globs": ["*.md"], "exclude_globs": [], "max_pages": 50},
        )

        with (
            patch.object(github, "resolve_ref", return_value="main"),
            patch.object(github, "fetch_stream") as mock_stream,
        ):
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            result = ingest_source(source_id=source.id, team_id=self.team.id)

        assert result is not None
        assert result.status == SourceStatus.READY
        docs = KnowledgeDocument.objects.unscoped().filter(source=source)
        assert docs.count() == 2
        chunks = KnowledgeChunk.objects.unscoped().filter(source=source)
        assert chunks.count() >= 2

    def test_ingest_empty_result_marks_error(self) -> None:
        tarball = _make_tarball({"src/code.py": "print('hello')"})

        source = KnowledgeSource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name="Test Repo",
            source_type=SourceType.URL,
            status=SourceStatus.PROCESSING,
            source_url="https://github.com/owner/repo",
            crawl_mode=CrawlMode.GITHUB_REPO,
            crawl_config={"include_globs": ["*.md"], "exclude_globs": [], "max_pages": 50},
        )

        with (
            patch.object(github, "resolve_ref", return_value="main"),
            patch.object(github, "fetch_stream") as mock_stream,
        ):
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            result = ingest_source(source_id=source.id, team_id=self.team.id)

        assert result is not None
        assert result.status == SourceStatus.ERROR
        assert "No matching files" in result.error_message


class TestGithubRefreshSource(BaseTest):
    def test_refresh_updates_changed_files(self) -> None:
        source = KnowledgeSource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name="Test Repo",
            source_type=SourceType.URL,
            status=SourceStatus.READY,
            source_url="https://github.com/owner/repo",
            crawl_mode=CrawlMode.GITHUB_REPO,
            crawl_config={"include_globs": ["*.md"], "exclude_globs": [], "max_pages": 50},
        )
        doc = KnowledgeDocument.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            source=source,
            stable_id="https://github.com/owner/repo/blob/main/README.md",
            title="README.md",
            content="Old content",
            content_hash="old_hash",
        )

        tarball = _make_tarball({"README.md": "New content"})

        with (
            patch.object(github, "resolve_ref", return_value="main"),
            patch.object(github, "fetch_stream") as mock_stream,
        ):
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            result = refresh_source(source_id=source.id, team_id=self.team.id)

        assert result is not None
        assert result.status == SourceStatus.READY
        doc.refresh_from_db()
        assert doc.content == "New content"

    def test_refresh_tombstones_removed_files(self) -> None:
        source = KnowledgeSource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name="Test Repo",
            source_type=SourceType.URL,
            status=SourceStatus.READY,
            source_url="https://github.com/owner/repo",
            crawl_mode=CrawlMode.GITHUB_REPO,
            crawl_config={"include_globs": ["*.md"], "exclude_globs": [], "max_pages": 50},
        )
        doc = KnowledgeDocument.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            source=source,
            stable_id="https://github.com/owner/repo/blob/main/DELETED.md",
            title="DELETED.md",
            content="This file will be removed",
            content_hash="some_hash",
        )

        tarball = _make_tarball({"README.md": "Still here"})

        with (
            patch.object(github, "resolve_ref", return_value="main"),
            patch.object(github, "fetch_stream") as mock_stream,
        ):
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=io.BytesIO(tarball))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_stream.return_value = mock_cm

            result = refresh_source(source_id=source.id, team_id=self.team.id)

        assert result is not None
        doc.refresh_from_db()
        assert doc.tombstoned_at is not None


class TestGithubSerializer(APIBaseTest):
    def test_create_github_source_validates_repo_url(self) -> None:
        data = {
            "name": "Test",
            "url": "https://not-github.com/owner/repo",
            "crawl_mode": "github_repo",
        }
        serializer = CreateCrawlSourceSerializer(data=data)
        assert not serializer.is_valid()
        assert "url" in serializer.errors

    @parameterized.expand(
        [
            (
                "defaults_to_docs_globs_without_ref",
                "https://github.com/owner/repo",
                None,
                ["*.md", "*.mdx", "*.markdown", "*.rst", "*.txt"],
                None,
            ),
            (
                "extracts_ref_from_tree_url",
                "https://github.com/owner/repo/tree/v1.2.3",
                None,
                ["*.md", "*.mdx", "*.markdown", "*.rst", "*.txt"],
                "v1.2.3",
            ),
            (
                "keeps_custom_include_globs",
                "https://github.com/owner/repo",
                ["*.py", "*.js"],
                ["*.py", "*.js"],
                None,
            ),
        ]
    )
    def test_create_github_source_builds_expected_crawl_config(
        self,
        _case: str,
        url: str,
        include_globs: list[str] | None,
        expected_include_globs: list[str],
        expected_ref: str | None,
    ) -> None:
        data: dict[str, object] = {
            "name": "Test",
            "url": url,
            "crawl_mode": "github_repo",
        }
        if include_globs is not None:
            data["include_globs"] = include_globs
        serializer = CreateCrawlSourceSerializer(data=data)
        assert serializer.is_valid(), serializer.errors
        internal = serializer.validated_data
        assert internal["crawl_config"]["include_globs"] == expected_include_globs
        assert internal["crawl_config"]["ref"] == expected_ref

    @parameterized.expand(
        [
            ("rejects_non_github_url", "https://docs.example.com", False, None),
            ("syncs_ref_from_tree_url", "https://github.com/owner/repo/tree/release", True, "release"),
        ]
    )
    def test_update_github_source_url_behavior(
        self,
        _case: str,
        updated_url: str,
        should_be_valid: bool,
        expected_ref: str | None,
    ) -> None:
        source = KnowledgeSource.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name="Repo source",
            source_type=SourceType.URL,
            status=SourceStatus.READY,
            source_url="https://github.com/owner/repo/tree/main",
            crawl_mode=CrawlMode.GITHUB_REPO,
            crawl_config={"include_globs": ["*.md"], "exclude_globs": [], "max_pages": 50, "ref": "main"},
        )

        serializer = UpdateUrlSourceSerializer(instance=source, data={"url": updated_url})
        if not should_be_valid:
            assert not serializer.is_valid()
            assert "url" in serializer.errors
            return

        assert serializer.is_valid(), serializer.errors
        internal = serializer.validated_data
        assert internal["crawl_config"]["ref"] == expected_ref
        # Existing custom globs remain intact when only the URL changes.
        assert "include_globs" not in internal["crawl_config"]


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestGithubSourceAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.api_url = f"/api/projects/{self.team.id}/business_knowledge/sources/"

    @patch("products.business_knowledge.backend.api.views.KnowledgeSourceViewSet._start_background_ingest")
    @patch("products.business_knowledge.backend.api.views.logic.claim_url_source")
    def test_create_github_source_via_api(self, mock_claim: MagicMock, mock_start: MagicMock, _ff: MagicMock) -> None:
        mock_claim.return_value = KnowledgeSource(
            id="00000000-0000-0000-0000-000000000001",
            team=self.team,
            name="Test Repo",
            source_type="url",
            status="processing",
            crawl_mode="github_repo",
            crawl_config={"include_globs": ["*.md", "*.mdx", "*.markdown", "*.rst", "*.txt"], "ref": None},
        )
        response = self.client.post(
            self.api_url,
            {
                "source_type": "url",
                "name": "Test Repo",
                "url": "https://github.com/owner/repo",
                "crawl_mode": "github_repo",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        call_kwargs = mock_claim.call_args.kwargs
        assert call_kwargs["crawl_mode"] == "github_repo"
        assert "include_globs" in call_kwargs["crawl_config"]
