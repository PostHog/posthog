from __future__ import annotations

import pytest

import yaml
from parameterized import parameterized

from .skill_frontmatter import (
    SkillSpecError,
    assemble_skill_md,
    strip_frontmatter,
    validate_allowed_tools,
    validate_compatibility,
    validate_description,
    validate_metadata_map,
    validate_skill_name,
    validate_skill_spec,
)


class TestSkillNameValidation:
    @parameterized.expand(
        [
            ("simple", "research"),
            ("with-hyphen", "deep-research"),
            ("with-digits", "tool-2"),
            ("single-char", "a"),
            ("max-length", "a" * 64),
        ]
    )
    def test_valid_names(self, _name: str, value: str) -> None:
        assert validate_skill_name(value) == value

    @parameterized.expand(
        [
            ("empty", ""),
            ("uppercase", "Research"),
            ("leading-hyphen", "-research"),
            ("trailing-hyphen", "research-"),
            ("consecutive-hyphens", "deep--research"),
            ("too-long", "a" * 65),
            ("slash", "@posthog/research"),
            ("space", "deep research"),
        ]
    )
    def test_invalid_names(self, _name: str, value: str) -> None:
        with pytest.raises(SkillSpecError):
            validate_skill_name(value)


class TestDescriptionValidation:
    def test_non_empty_ok(self) -> None:
        assert validate_description("does a thing") == "does a thing"

    @parameterized.expand([("empty", ""), ("whitespace", "   \n\t ")])
    def test_empty_rejected(self, _name: str, value: str) -> None:
        with pytest.raises(SkillSpecError):
            validate_description(value)

    def test_too_long_rejected(self) -> None:
        with pytest.raises(SkillSpecError):
            validate_description("x" * 1025)

    def test_max_length_ok(self) -> None:
        assert validate_description("x" * 1024)


class TestCompatibilityValidation:
    def test_blank_ok(self) -> None:
        assert validate_compatibility("") == ""

    def test_max_ok(self) -> None:
        assert validate_compatibility("x" * 500)

    def test_too_long_rejected(self) -> None:
        with pytest.raises(SkillSpecError):
            validate_compatibility("x" * 501)


class TestMetadataValidation:
    @parameterized.expand([("none", None), ("empty-str", ""), ("empty-dict", {})])
    def test_empty_returns_dict(self, _name: str, value: object) -> None:
        assert validate_metadata_map(value) == {}

    def test_string_map_ok(self) -> None:
        assert validate_metadata_map({"version": "1", "author": "ph"}) == {"version": "1", "author": "ph"}

    @parameterized.expand(
        [
            ("list", ["a"]),
            ("non-string-value", {"version": 1}),
            ("nested", {"k": {"deep": "v"}}),
        ]
    )
    def test_invalid_rejected(self, _name: str, value: object) -> None:
        with pytest.raises(SkillSpecError):
            validate_metadata_map(value)


class TestAllowedToolsValidation:
    @parameterized.expand([("none", None), ("empty", [])])
    def test_empty_returns_list(self, _name: str, value: object) -> None:
        assert validate_allowed_tools(value) == []

    def test_list_ok(self) -> None:
        assert validate_allowed_tools(["Read", "Bash"]) == ["Read", "Bash"]

    @parameterized.expand(
        [
            ("not-list", "Read Bash"),
            ("non-string-entry", ["Read", 3]),
            ("entry-with-space", ["Read Bash"]),
        ]
    )
    def test_invalid_rejected(self, _name: str, value: object) -> None:
        with pytest.raises(SkillSpecError):
            validate_allowed_tools(value)


class TestValidateSkillSpec:
    def test_happy_path(self) -> None:
        validate_skill_spec(
            name="research",
            description="how to research",
            compatibility="Requires git",
            metadata={"version": "1"},
            allowed_tools=["Read"],
        )

    def test_propagates_field_pointer(self) -> None:
        with pytest.raises(SkillSpecError) as exc:
            validate_skill_spec(name="research", description="")
        assert exc.value.field == "description"


class TestStripFrontmatter:
    def test_strips_leading_block(self) -> None:
        assert strip_frontmatter("---\nname: x\n---\n\n# Body") == "# Body"

    def test_no_frontmatter_untouched(self) -> None:
        assert strip_frontmatter("# Body\nmore") == "# Body\nmore"

    def test_only_strips_first_block(self) -> None:
        body = "---\nname: x\n---\n\nintro\n\n---\n\na horizontal rule section"
        out = strip_frontmatter(body)
        assert out.startswith("intro")
        assert "horizontal rule" in out


class TestAssembleSkillMd:
    def _front(self, skill_md: str) -> dict:
        # Parse back the leading frontmatter block for structural assertions.
        assert skill_md.startswith("---\n")
        _, fm, _ = skill_md.split("---\n", 2)
        return yaml.safe_load(fm)

    def test_minimal_uses_alias_as_name(self) -> None:
        md = assemble_skill_md(alias="research", description="d", body="# Hello")
        front = self._front(md)
        assert front == {"name": "research", "description": "d"}
        assert md.rstrip().endswith("# Hello")

    @parameterized.expand([("uppercase", "Bad"), ("underscore", "bad_name"), ("slash", "a/b"), ("traversal", "..")])
    def test_rejects_invalid_alias_at_emission(self, _name: str, alias: str) -> None:
        # The alias becomes the spec `name`; an invalid one is rejected here,
        # independent of the freeze-time `_require_alias` gate.
        with pytest.raises(SkillSpecError):
            assemble_skill_md(alias=alias, description="d", body="b")

    def test_omits_empty_optionals(self) -> None:
        md = assemble_skill_md(alias="r", description="d", body="b", license="", compatibility="")
        front = self._front(md)
        assert "license" not in front
        assert "compatibility" not in front
        assert "allowed-tools" not in front
        assert "metadata" not in front

    def test_includes_all_fields(self) -> None:
        md = assemble_skill_md(
            alias="r",
            description="d",
            body="b",
            license="Apache-2.0",
            compatibility="Requires git",
            metadata={"version": "1"},
            allowed_tools=["Read", "Bash"],
        )
        front = self._front(md)
        assert front["license"] == "Apache-2.0"
        assert front["compatibility"] == "Requires git"
        assert front["metadata"] == {"version": "1"}
        # allowed-tools is the spec's space-separated string, not a list.
        assert front["allowed-tools"] == "Read Bash"

    def test_strips_prior_frontmatter_in_body(self) -> None:
        # An author who pasted a full SKILL.md gets a single authoritative block.
        body = "---\nname: stale\ndescription: stale desc\n---\n\n# Real body"
        md = assemble_skill_md(alias="r", description="real desc", body=body)
        assert md.count("---\n") == 2  # exactly one frontmatter block
        front = self._front(md)
        assert front["name"] == "r"
        assert front["description"] == "real desc"
        assert "# Real body" in md
        assert "stale" not in md

    def test_name_matches_parent_dir_alias(self) -> None:
        # The spec name must equal the bundle dir — i.e. the alias, not the
        # registry name (which may carry the @posthog/ prefix).
        md = assemble_skill_md(alias="research", description="d", body="b")
        assert self._front(md)["name"] == "research"
