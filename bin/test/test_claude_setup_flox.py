import os
import hashlib
import tempfile
import subprocess
from pathlib import Path

import unittest

REPOSITORY = Path(__file__).resolve().parents[2]
HOOK = REPOSITORY / ".claude/hooks/setup-flox.sh"


class TestClaudeSetupFlox(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.worktree = self.root / "worktree"
        subprocess.run(
            ["git", "-C", str(REPOSITORY), "worktree", "add", "--detach", "--no-checkout", str(self.worktree), "HEAD"],
            check=True,
            capture_output=True,
        )
        self.addCleanup(self.remove_worktree)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.marker = self.root / "activation-called"
        executable = self.bin / "flox"
        executable.write_text('#!/bin/sh\nprintf invoked > "$FLOX_TEST_MARKER"\nprintf "PATH=/usr/bin:/bin\\n"\n')
        executable.chmod(0o755)
        self.env_file = self.root / "claude-env"

    def remove_worktree(self) -> None:
        subprocess.run(
            ["git", "-C", str(REPOSITORY), "worktree", "remove", "--force", str(self.worktree)],
            check=True,
            capture_output=True,
        )

    def run_hook(self, project: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(HOOK)],
            cwd=project,
            env={
                **os.environ,
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "CLAUDE_PROJECT_DIR": str(project),
                "CLAUDE_ENV_FILE": str(self.env_file),
                "CLAUDE_CODE_REMOTE": "false",
                "FLOX_TEST_MARKER": str(self.marker),
            },
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )

    def prepare_manifest(self, project: Path) -> Path:
        manifest = project / ".flox/env/manifest.toml"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("version = 1\n")
        return manifest

    def test_worktree_defers_activation_without_a_valid_cache(self) -> None:
        self.prepare_manifest(self.worktree)
        cache = self.worktree / ".flox/cache/claude-env-cache"
        for cached_hash in (None, "outdated"):
            with self.subTest(cached_hash=cached_hash):
                if cached_hash:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(f"# manifest-hash: {cached_hash}\nexport EXAMPLE_CACHED_ENV=stale\n")
                result = self.run_hook(self.worktree)
                self.assertFalse(self.marker.exists())
                self.assertFalse(self.env_file.exists())
                self.assertIn("flox activate -- bash -c '<command>'", result.stdout)
                self.assertIn("Start editing without installing dependencies", result.stdout)

    def test_worktree_loads_a_valid_cache_without_activation(self) -> None:
        manifest = self.prepare_manifest(self.worktree)
        manifest_hash = hashlib.md5(manifest.read_bytes(), usedforsecurity=False).hexdigest()
        cache = self.worktree / ".flox/cache/claude-env-cache"
        cache.parent.mkdir(parents=True)
        cache.write_text(f"# manifest-hash: {manifest_hash}\nexport EXAMPLE_CACHED_ENV=ready\n")
        self.run_hook(self.worktree)
        self.assertFalse(self.marker.exists())
        self.assertIn("export EXAMPLE_CACHED_ENV=ready", self.env_file.read_text())

    def test_ordinary_checkout_still_activates_flox(self) -> None:
        checkout = self.root / "main-checkout"
        subprocess.run(["git", "init", str(checkout)], check=True, capture_output=True)
        self.prepare_manifest(checkout)
        self.run_hook(checkout)
        self.assertTrue(self.marker.exists())
        self.assertIn("export PATH=", self.env_file.read_text())
        self.assertTrue((checkout / ".flox/cache/claude-env-cache").exists())


if __name__ == "__main__":
    unittest.main()
