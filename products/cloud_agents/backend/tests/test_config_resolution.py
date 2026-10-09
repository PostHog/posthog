import dataclasses
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cloud_agents.backend.facade.contracts import (
    InvalidInput,
    PresetDTO,
    RepositoryRef,
    RepositoryRequired,
    ResolvedRunConfig,
    RunCreateInput,
    TeamSettingsDTO,
)
from products.cloud_agents.backend.facade.enums import (
    CloudAgentReasoningEffort,
    InferenceMode,
    SizeName,
    SizeShape,
    size_shape,
)
from products.cloud_agents.backend.logic.config_resolution import render_prompt, resolve_run_config

PRESET_ID = UUID("01900000-0000-7000-8000-000000000001")
NOW = datetime(2026, 1, 1, tzinfo=UTC)
APP = [RepositoryRef(name="acme/app")]
BASE: dict[str, Any] = {"repositories": APP}

EMPTY_TEAM = TeamSettingsDTO(
    repositories=None,
    model=None,
    reasoning_effort=None,
    size=None,
    inference=None,
    instructions=None,
    create_pr=None,
    idle_minutes=None,
    output_schema=None,
    default_preset_id=None,
    max_concurrent_runs=5,
    create_rate_per_hour=60,
    updated_at=None,
)
EMPTY_PRESET = PresetDTO(
    id=PRESET_ID,
    name="default",
    description="",
    repositories=None,
    model=None,
    reasoning_effort=None,
    size=None,
    inference=None,
    instructions=None,
    create_pr=None,
    idle_minutes=None,
    output_schema=None,
    tags=[],
    created_by_id=None,
    created_at=NOW,
    updated_at=NOW,
)


def _schema(field: str) -> dict[str, Any]:
    return {"type": "object", "properties": {field: {"type": "string"}}}


def _repositories(name: str, branch: str | None = None) -> list[RepositoryRef]:
    return [RepositoryRef(name=name, initial_branch=branch)]


# field, call value, preset value, team value, product default
PRECEDENCE_FIELDS: list[tuple[str, Any, Any, Any, Any]] = [
    ("model", "call-model", "preset-model", "team-model", None),
    (
        "reasoning_effort",
        CloudAgentReasoningEffort.LOW,
        CloudAgentReasoningEffort.HIGH,
        CloudAgentReasoningEffort.MAX,
        None,
    ),
    ("size", SizeName.S_1X2, SizeName.S_2X4, SizeName.S_8X32, SizeName.S_4X16),
    # Adjacent levels differ, so a level cannot pass on the value of the level below it.
    ("create_pr", False, True, False, True),
    (
        "inference",
        InferenceMode.OWN_SUBSCRIPTION,
        InferenceMode.POSTHOG,
        InferenceMode.OWN_SUBSCRIPTION,
        InferenceMode.AUTO,
    ),
    ("idle_minutes", 5, 20, 30, 10),
    ("output_schema", _schema("call"), _schema("preset"), _schema("team"), None),
]


def _resolve(call: dict[str, Any], preset: dict[str, Any] | None, team: dict[str, Any]) -> ResolvedRunConfig:
    return resolve_run_config(
        RunCreateInput(prompt="Fix the bug", **call),
        dataclasses.replace(EMPTY_PRESET, **preset) if preset is not None else None,
        dataclasses.replace(EMPTY_TEAM, **team),
    )


class TestResolveRunConfig(SimpleTestCase):
    @parameterized.expand([(field, *values) for field, *values in PRECEDENCE_FIELDS])
    def test_field_precedence(self, field: str, call: Any, preset: Any, team: Any, default: Any) -> None:
        assert getattr(_resolve({**BASE, field: call}, {field: preset}, {field: team}), field) == call
        assert getattr(_resolve(BASE, {field: preset}, {field: team}), field) == preset
        assert getattr(_resolve(BASE, {}, {field: team}), field) == team
        assert getattr(_resolve(BASE, None, {field: team}), field) == team
        assert getattr(_resolve(BASE, {}, {}), field) == default

    @parameterized.expand(
        [
            (
                "call",
                _repositories("call/repo", "dev"),
                _repositories("preset/repo"),
                _repositories("team/repo"),
                "call",
            ),
            ("preset", None, _repositories("preset/repo", "dev"), _repositories("team/repo"), "preset"),
            ("empty_call_list", [], _repositories("preset/repo", "dev"), _repositories("team/repo"), "preset"),
            ("team", None, None, _repositories("team/repo", "dev"), "team"),
            ("empty_preset_list", None, [], _repositories("team/repo", "dev"), "team"),
        ]
    )
    def test_repositories_come_whole_from_the_first_level_that_names_one(
        self,
        _name: str,
        call: list[RepositoryRef] | None,
        preset: list[RepositoryRef] | None,
        team: list[RepositoryRef] | None,
        expected: str,
    ) -> None:
        config = _resolve({"repositories": call}, {"repositories": preset}, {"repositories": team})
        # The branch comes with its repository, and never from a different level.
        assert config.repositories == _repositories(f"{expected}/repo", "dev")

    @parameterized.expand([("no_preset", None), ("empty_preset", {}), ("empty_list", {"repositories": []})])
    def test_missing_repository_is_rejected(self, _name: str, preset: dict | None) -> None:
        with self.assertRaises(RepositoryRequired) as raised:
            _resolve({}, preset, {})
        assert (raised.exception.attr, raised.exception.code) == ("repositories", "repository_required")

    @parameterized.expand([("call",), ("preset",), ("team",)])
    def test_more_than_one_repository_is_rejected(self, level: str) -> None:
        two = [RepositoryRef(name="acme/app"), RepositoryRef(name="acme/web")]
        levels: dict[str, dict[str, Any]] = {"call": {}, "preset": {}, "team": {}}
        levels[level] = {"repositories": two}
        with self.assertRaises(InvalidInput) as raised:
            _resolve(levels["call"], levels["preset"], levels["team"])
        assert (raised.exception.attr, raised.exception.message) == (
            "repositories",
            "Only one repository is supported for now.",
        )

    @parameterized.expand(
        [
            ("union_keeps_first_position", ["a", "b"], ["b", "c"], ["a", "b", "c"]),
            ("preset_only", ["a"], None, ["a"]),
            ("call_only", [], ["z", "a"], ["z", "a"]),
            ("none", [], None, []),
        ]
    )
    def test_tags_union_is_order_stable(
        self, _name: str, preset_tags: list[str], call_tags: list[str] | None, expected: list[str]
    ) -> None:
        config = _resolve({**BASE, "tags": call_tags}, {"tags": preset_tags}, {})
        assert config.tags == expected

    @parameterized.expand(
        [
            ("all_levels", "call", "preset", "team", "team\n\npreset\n\ncall"),
            ("skips_missing_levels", "call", None, "team", "team\n\ncall"),
            ("skips_blank_levels", "call", "  ", None, "call"),
            ("none", None, None, None, None),
        ]
    )
    def test_instructions_join_team_then_preset_then_call(
        self, _name: str, call: str | None, preset: str | None, team: str | None, expected: str | None
    ) -> None:
        config = _resolve({**BASE, "instructions": call}, {"instructions": preset}, {"instructions": team})
        assert config.instructions == expected

    @parameterized.expand([(1, True), (120, True), (0, False), (121, False)])
    def test_idle_minutes_bounds(self, minutes: int, valid: bool) -> None:
        # The team level, because an API serializer does not check a value that a row already holds.
        if valid:
            assert _resolve(BASE, None, {"idle_minutes": minutes}).idle_minutes == minutes
        else:
            with self.assertRaises(InvalidInput) as raised:
                _resolve(BASE, None, {"idle_minutes": minutes})
            assert raised.exception.attr == "idle_minutes"

    @parameterized.expand(
        [
            ("not_an_object_schema", {"type": "string"}),
            ("no_type", {"properties": {"answer": {"type": "string"}}}),
            ("reserved_property", {"type": "object", "properties": {"pr_url": {"type": "string"}}}),
            ("not_a_json_schema", {"type": "object", "properties": {"answer": {"type": "text"}}}),
            ("too_large", {"type": "object", "description": "x" * 20000}),
        ]
    )
    def test_output_schema_that_tasks_cannot_use_is_rejected(self, _name: str, schema: dict[str, Any]) -> None:
        with self.assertRaises(InvalidInput) as raised:
            _resolve(BASE, None, {"output_schema": schema})
        assert raised.exception.attr == "output_schema"

    def test_preset_id(self) -> None:
        config = _resolve(BASE, {"description": "UI work"}, {})
        assert config.preset_id == PRESET_ID
        assert _resolve(BASE, None, {}).preset_id is None

    def test_config_json_round_trip(self) -> None:
        config = _resolve(
            {
                "repositories": _repositories("acme/app", "main"),
                "tags": ["a"],
                "size": SizeName.S_16X64,
                "reasoning_effort": CloudAgentReasoningEffort.HIGH,
                "output_schema": _schema("answer"),
            },
            {"instructions": "Use pnpm"},
            {},
        )
        assert ResolvedRunConfig.from_json(config.to_json()) == config

    @parameterized.expand([("with_instructions", "Use pnpm", True), ("without_instructions", None, False)])
    def test_render_prompt_puts_instructions_above_prompt(
        self, _name: str, instructions: str | None, has_block: bool
    ) -> None:
        config = _resolve({**BASE, "instructions": instructions}, None, {})
        rendered = render_prompt(config, "Fix the bug")
        if has_block:
            assert rendered.index("Use pnpm") < rendered.index("Fix the bug")
        else:
            assert rendered == "Fix the bug"

    @parameterized.expand([(SizeName.S_1X2, (1, 2)), (SizeName.S_4X16, (4, 16)), (SizeName.S_16X64, (16, 64))])
    def test_size_shape(self, size: SizeName, expected: tuple[int, int]) -> None:
        assert size_shape(size) == SizeShape(vcpu=expected[0], memory_gib=expected[1])
