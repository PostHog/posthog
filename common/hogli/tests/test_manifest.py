"""Tests for manifest loading and extends resolution."""

from __future__ import annotations

from hogli.core.manifest import Manifest


class TestExtendsResolution:
    """Test extends: inheritance pattern."""

    def test_resolve_extends_merges_base_config(self) -> None:
        """Child command inherits all fields from parent."""
        manifest = Manifest()

        parent = manifest.get_command_config("docker:services:up")
        child = manifest.get_command_config("docker:services:up:minimal")

        assert parent is not None
        assert child is not None
        # Child inherits description
        assert child.get("description") == parent.get("description")
        # Child inherits services
        assert child.get("services") == parent.get("services")
        # Child has its own cmd
        assert "minimal" in child.get("cmd", "")
        assert "minimal" not in parent.get("cmd", "")

    def test_resolve_extends_preserves_extends_key(self) -> None:
        """Extends key is preserved for tree display."""
        manifest = Manifest()

        child = manifest.get_command_config("docker:services:up:minimal")

        assert child is not None
        assert child.get("extends") == "docker:services:up"

    def test_resolve_extends_child_overrides_parent(self) -> None:
        """Child fields override parent fields."""
        manifest = Manifest()

        parent = manifest.get_command_config("docker:services:up")
        child = manifest.get_command_config("docker:services:up:minimal")

        assert parent is not None
        assert child is not None
        # Commands are different
        assert parent.get("cmd") != child.get("cmd")
        assert "docker-compose.dev.yml" in parent.get("cmd", "")
        assert "docker-compose.dev-minimal.yml" in child.get("cmd", "")


class TestGetChildrenForCommand:
    """Test children lookup."""

    def test_returns_children_for_parent(self) -> None:
        """Returns list of commands that extend the parent."""
        manifest = Manifest()

        children = manifest.get_children_for_command("docker:services:up")

        assert "docker:services:up:minimal" in children

    def test_returns_empty_for_leaf_command(self) -> None:
        """Returns empty list for commands with no children."""
        manifest = Manifest()

        children = manifest.get_children_for_command("docker:services:up:minimal")

        assert children == []

    def test_returns_empty_for_nonexistent_command(self) -> None:
        """Returns empty list for unknown commands."""
        manifest = Manifest()

        children = manifest.get_children_for_command("nonexistent:command")

        assert children == []

    def test_children_are_sorted(self) -> None:
        """Children are returned in sorted order."""
        manifest = Manifest()

        children = manifest.get_children_for_command("docker:services:up")

        assert children == sorted(children)
