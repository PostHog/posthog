"""Build the OpenFGA model from products/authz/model/ and check it against the model rules.

Run products/authz/generate_model.sh rather than this module. The script also converts the model to JSON.
"""

import re
import sys
import json
import hashlib
import tomllib
import argparse
from collections.abc import Mapping
from functools import cached_property
from pathlib import Path
from typing import TypedDict

import yaml

from posthog.dataclasses import frozen

from products.authz.backend.facade.enums import Action, Level, ResourceType

PRODUCT_DIR = Path(__file__).resolve().parents[2]
SOURCE_DIR = PRODUCT_DIR / "model"
MODEL_PATH = PRODUCT_DIR / "model.fga"
JSON_MODEL_PATH = PRODUCT_DIR / "openfga_model.json"
MODEL_TESTS_PATH = PRODUCT_DIR / "model.fga.yaml"

TEMPLATE_TYPE = "resource"
PERMISSION_PREFIX = "can_"
BANNER = "# Generated from products/authz/model/ by products/authz/generate_model.sh. Do not edit."
DIGEST_PREFIX = "# Content digest: "
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
DEFINE_PATTERN = re.compile(r"^\s+define (\w+):\s*(.+?)\s*$")
FROM_PATTERN = re.compile(r"(\w+) from (\w+)")
IDENTIFIER_PATTERN = re.compile(r"[a-z_][a-z0-9_]*")
OPERATOR_WORDS = frozenset({"or", "and", "but", "not", "from"})
COMPLEX_PATTERN = re.compile(r"\bbut not\b|\band\b|:\*")


class ModelSourceError(Exception):
    pass


@frozen
class Relation:
    name: str
    definition: str
    comments: tuple[str, ...] = ()


@frozen
class TypeDefinition:
    name: str
    relations: tuple[Relation, ...]

    def relation_names(self) -> frozenset[str]:
        return frozenset(relation.name for relation in self.relations)


@frozen
class ResourceSpec:
    type: str
    shareable: bool
    relations: tuple[Relation, ...]


@frozen
class ModelLimits:
    core_relations: Mapping[str, int]
    resource_relations: Mapping[str, int]
    complex_resource_relations: Mapping[str, frozenset[str]]
    unmapped_permissions: Mapping[str, frozenset[str]]


@frozen
class RelationKey:
    type: str
    relation: str


@frozen
class Assertion:
    type: str
    permission: str
    expected: bool


@frozen
class ModelTests:
    """What model.fga.yaml covers: the permission results it checks and the relations its tuples write."""

    assertions: frozenset[Assertion]
    written: frozenset[RelationKey]


def parse_types(dsl: str) -> tuple[TypeDefinition, ...]:
    """Parse the type definitions of an OpenFGA DSL model. Conditions are skipped."""
    types: list[TypeDefinition] = []
    name: str | None = None
    relations: list[Relation] = []
    comments: list[str] = []
    in_condition = False
    for line in dsl.splitlines():
        stripped = line.strip()
        if in_condition:
            in_condition = not stripped.endswith("}")
            continue
        if stripped.startswith("#"):
            comments.append(stripped.removeprefix("#").strip())
            continue
        if line.startswith("type "):
            if name is not None:
                types.append(TypeDefinition(name=name, relations=tuple(relations)))
            name, relations = line.split()[1], []
        elif line.startswith("condition "):
            in_condition = not stripped.endswith("}")
        elif (match := DEFINE_PATTERN.match(line)) and name is not None:
            definition = re.sub(r"\s+#.*$", "", match.group(2))
            relations.append(Relation(name=match.group(1), definition=definition, comments=tuple(comments)))
        comments = [] if stripped else comments
    if name is not None:
        types.append(TypeDefinition(name=name, relations=tuple(relations)))
    return tuple(types)


def render_type(definition: TypeDefinition) -> str:
    lines = [f"type {definition.name}", "  relations"]
    for relation in definition.relations:
        lines.extend(f"    # {comment}" for comment in relation.comments)
        lines.append(f"    define {relation.name}: {relation.definition}")
    return "\n".join(lines)


def content_digest(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()[:16]


class ModelBuilder:
    def __init__(self, source_dir: Path = SOURCE_DIR) -> None:
        self.source_dir = source_dir

    def core(self) -> str:
        return (self.source_dir / "core.fga").read_text().strip()

    def core_types(self) -> tuple[TypeDefinition, ...]:
        return parse_types(self.core())

    def template(self) -> TypeDefinition:
        types = parse_types((self.source_dir / "resource.fga").read_text())
        if [definition.name for definition in types] != [TEMPLATE_TYPE]:
            raise ModelSourceError(f"resource.fga must define exactly one type, named {TEMPLATE_TYPE!r}")
        return types[0]

    def limits(self) -> ModelLimits:
        data = tomllib.loads((self.source_dir / "limits.toml").read_text())
        return ModelLimits(
            core_relations=data.get("core_relations", {}),
            resource_relations=data.get("resource_relations", {}),
            complex_resource_relations={k: frozenset(v) for k, v in data.get("complex_resource_relations", {}).items()},
            unmapped_permissions={k: frozenset(v) for k, v in data.get("unmapped_permissions", {}).items()},
        )

    def resources(self) -> tuple[ResourceSpec, ...]:
        data = tomllib.loads((self.source_dir / "resources.toml").read_text())
        return tuple(self._resource_spec(name, entry) for name, entry in data.items())

    def build(self) -> str:
        template = self.template()
        core_names = {definition.name for definition in self.core_types()}
        specs = self.resources()
        for spec in specs:
            if spec.type in core_names or spec.type == TEMPLATE_TYPE:
                raise ModelSourceError(f"resources.toml: {spec.type!r} is already a core type")
        resources = [self.expand(template, spec) for spec in specs]
        body = "\n\n".join([self.core(), *(render_type(resource) for resource in resources)]) + "\n"
        return f"{BANNER}\n{DIGEST_PREFIX}{content_digest(body)}\n{body}"

    def write(self, model_path: Path = MODEL_PATH, *, force: bool = False) -> None:
        model = self.build()
        current = model_path.read_text() if model_path.exists() else None
        if current == model:
            return
        if current is not None and not force and not self._is_unedited_output(current):
            raise ModelSourceError(
                f"{model_path.name} has changes that did not come from the model build. Move them into "
                f"products/authz/model/, then run products/authz/generate_model.sh. Pass --force to overwrite them."
            )
        model_path.write_text(model)

    @staticmethod
    def expand(template: TypeDefinition, spec: ResourceSpec) -> TypeDefinition:
        """Copy the template for one resource. Added permissions go last, other added relations before the permissions."""
        relations = list(template.relations)
        template_names = template.relation_names()
        for relation in spec.relations:
            if relation.name in template_names:
                if not relation.name.startswith(PERMISSION_PREFIX):
                    raise ModelSourceError(
                        f"{spec.type}.{relation.name}: a resource can replace only template permissions (can_*)"
                    )
                relations = [relation if existing.name == relation.name else existing for existing in relations]
            elif relation.name.startswith(PERMISSION_PREFIX):
                relations.append(relation)
            else:
                first_permission = next(
                    (index for index, existing in enumerate(relations) if existing.name.startswith(PERMISSION_PREFIX)),
                    len(relations),
                )
                relations.insert(first_permission, relation)
        if spec.shareable:
            relations.append(Relation(name="can_share", definition="can_edit"))
        return TypeDefinition(name=spec.type, relations=tuple(relations))

    @staticmethod
    def _resource_spec(name: str, entry: object) -> ResourceSpec:
        if not isinstance(entry, dict) or set(entry) - {"shareable", "relations"}:
            raise ModelSourceError(f"{name}: an entry is a table with only the keys shareable and relations")
        shareable = entry.get("shareable", False)
        raw_relations = entry.get("relations", {})
        if not isinstance(shareable, bool) or not isinstance(raw_relations, dict):
            raise ModelSourceError(f"{name}: shareable must be a boolean and relations must be a table")
        if shareable and "can_share" in raw_relations:
            raise ModelSourceError(f"{name}.can_share: remove it or remove shareable, not both")
        relations = []
        for relation_name, fields in raw_relations.items():
            if (
                not NAME_PATTERN.match(relation_name)
                or not isinstance(fields, dict)
                or set(fields) != {"definition", "why"}
                or not all(isinstance(value, str) and value.strip() for value in fields.values())
            ):
                raise ModelSourceError(
                    f"{name}.{relation_name}: a relation has a lowercase name, a definition and a why, and nothing else"
                )
            relations.append(
                Relation(name=relation_name, definition=fields["definition"].strip(), comments=(fields["why"].strip(),))
            )
        return ResourceSpec(type=name, shareable=shareable, relations=tuple(relations))

    @staticmethod
    def _is_unedited_output(model: str) -> bool:
        banner, _, rest = model.partition("\n")
        digest_line, _, body = rest.partition("\n")
        return banner == BANNER and digest_line == f"{DIGEST_PREFIX}{content_digest(body)}"


class ModelRules:
    """The rules that keep the model small. limits.toml holds the agreed exceptions, and each rule reports stale ones."""

    def __init__(
        self,
        *,
        model: str,
        builder: ModelBuilder,
        json_relations: Mapping[str, frozenset[str]],
        tests: ModelTests,
    ) -> None:
        self.model = model
        self.builder = builder
        self.json_relations = json_relations
        self.tests = tests
        self.types = {definition.name: definition for definition in parse_types(model)}

    @cached_property
    def core_names(self) -> tuple[str, ...]:
        return tuple(definition.name for definition in self.builder.core_types())

    @cached_property
    def resources(self) -> tuple[ResourceSpec, ...]:
        return self.builder.resources()

    @cached_property
    def limits(self) -> ModelLimits:
        return self.builder.limits()

    @classmethod
    def load(cls) -> "ModelRules":
        return cls(
            model=MODEL_PATH.read_text(),
            builder=ModelBuilder(),
            json_relations=relations_from_json(json.loads(JSON_MODEL_PATH.read_text())),
            tests=read_model_tests(yaml.safe_load(MODEL_TESTS_PATH.read_text())),
        )

    def problems(self) -> list[str]:
        try:
            built = self.builder.build()
        except ModelSourceError as error:
            return [str(error)]
        if self.model != built:
            return ["model.fga does not match its sources. Run products/authz/generate_model.sh."]
        return [
            *self._json_matches_model(),
            *self._resources_are_resource_types(),
            *self._core_sizes_match_limits(),
            *self._resource_changes_match_limits(),
            *self._complex_relations_match_limits(),
            *self._permissions_map_to_actions(),
            *self._relations_reach_a_permission(),
            *self._permissions_are_tested(),
            *self._stored_relations_are_tested(),
        ]

    def _json_matches_model(self) -> list[str]:
        model_types = {name: definition.relation_names() for name, definition in self.types.items()}
        if dict(self.json_relations) != model_types:
            return ["openfga_model.json does not match model.fga. Run products/authz/generate_model.sh."]
        return []

    def _resources_are_resource_types(self) -> list[str]:
        known = {resource_type.value for resource_type in ResourceType}
        return [
            f"resources.toml: {spec.type!r} is not a ResourceType value in products/authz/backend/facade/enums.py."
            for spec in self.resources
            if spec.type not in known
        ]

    def _core_sizes_match_limits(self) -> list[str]:
        actual = {name: len(self.types[name].relations) for name in self.core_names}
        return _compare("core_relations", actual, self.limits.core_relations, "relations in this core type")

    def _resource_changes_match_limits(self) -> list[str]:
        actual = {spec.type: len(spec.relations) for spec in self.resources if spec.relations}
        return _compare(
            "resource_relations", actual, self.limits.resource_relations, "relations this resource adds or replaces"
        )

    def _complex_relations_match_limits(self) -> list[str]:
        actual = {
            spec.type: frozenset(r.name for r in spec.relations if COMPLEX_PATTERN.search(r.definition))
            for spec in self.resources
        }
        actual = {name: names for name, names in actual.items() if names}
        return _compare(
            "complex_resource_relations",
            actual,
            self.limits.complex_resource_relations,
            "resource relations with 'but not', 'and' or a type:* wildcard",
        )

    def _permissions_map_to_actions(self) -> list[str]:
        actions = {action.value for action in Action}
        actual = {
            name: frozenset(
                relation.name
                for relation in definition.relations
                if relation.name.startswith(PERMISSION_PREFIX)
                and relation.name.removeprefix(PERMISSION_PREFIX) not in actions
            )
            for name, definition in self.types.items()
        }
        actual = {name: names for name, names in actual.items() if names}
        return _compare(
            "unmapped_permissions", actual, self.limits.unmapped_permissions, "permissions without an SDK Action"
        )

    def _relations_reach_a_permission(self) -> list[str]:
        levels = {level.value for level in Level}
        definitions = {
            RelationKey(type=name, relation=relation.name): relation.definition
            for name, definition in self.types.items()
            for relation in definition.relations
        }
        pending = [key for key in definitions if key.relation.startswith(PERMISSION_PREFIX) or key.relation in levels]
        reached: set[RelationKey] = set()
        while pending:
            key = pending.pop()
            if key in reached or key not in definitions:
                continue
            reached.add(key)
            pending.extend(self._references(key, definitions))
        return [
            f"{key.type}.{key.relation}: no permission (can_*) or SDK Level uses this relation. Remove it."
            for key in sorted(set(definitions) - reached, key=lambda key: (key.type, key.relation))
        ]

    @staticmethod
    def _references(key: RelationKey, definitions: Mapping[RelationKey, str]) -> list[RelationKey]:
        definition = definitions[key]
        references = []
        for restriction in re.findall(r"\[([^\]]*)\]", definition):
            for item in restriction.split(","):
                subject = item.split(" with ")[0].strip()
                if "#" in subject:
                    subject_type, relation = subject.split("#")
                    references.append(RelationKey(type=subject_type, relation=relation))
        expression = re.sub(r"\[[^\]]*\]", " ", definition)
        for target, tupleset in FROM_PATTERN.findall(expression):
            tupleset_key = RelationKey(type=key.type, relation=tupleset)
            references.append(tupleset_key)
            parents = re.findall(r"\[([^\]]*)\]", definitions.get(tupleset_key, ""))
            for parent in (item.split(" with ")[0].strip() for group in parents for item in group.split(",")):
                references.append(RelationKey(type=parent.split("#")[0].split(":")[0], relation=target))
        expression = FROM_PATTERN.sub(" ", expression)
        references.extend(
            RelationKey(type=key.type, relation=word)
            for word in IDENTIFIER_PATTERN.findall(expression)
            if word not in OPERATOR_WORDS
        )
        return references

    def _permissions_are_tested(self) -> list[str]:
        return [
            f"{name}.{relation.name}: model.fga.yaml has no check that expects {str(expected).lower()}. Add one."
            for name, definition in self.types.items()
            for relation in definition.relations
            if relation.name.startswith(PERMISSION_PREFIX)
            for expected in (True, False)
            if Assertion(type=name, permission=relation.name, expected=expected) not in self.tests.assertions
        ]

    def _stored_relations_are_tested(self) -> list[str]:
        return [
            f"{name}.{relation.name}: no tuple in model.fga.yaml writes this relation. Add a test that uses it."
            for name, definition in self.types.items()
            for relation in definition.relations
            if "[" in relation.definition and RelationKey(type=name, relation=relation.name) not in self.tests.written
        ]


def relations_from_json(json_model: dict[str, list[dict[str, dict[str, object]]]]) -> dict[str, frozenset[str]]:
    return {
        str(definition["type"]): frozenset(definition.get("relations") or {})
        for definition in json_model.get("type_definitions", [])
    }


class _TestTuple(TypedDict):
    user: str
    relation: str
    object: str


class _TestCheck(TypedDict, total=False):
    user: str
    object: str
    objects: list[str]
    assertions: dict[str, bool]


class _TestCase(TypedDict, total=False):
    name: str
    tuples: list[_TestTuple]
    check: list[_TestCheck]


class _TestFile(TypedDict, total=False):
    tuples: list[_TestTuple]
    tests: list[_TestCase]


def read_model_tests(tests: _TestFile) -> ModelTests:
    assertions = set()
    tuples = list(tests.get("tuples", []))
    for test in tests.get("tests", []):
        tuples.extend(test.get("tuples", []))
        for check in test.get("check", []):
            targets = check.get("objects") or [check.get("object", "")]
            for target in targets:
                for permission, expected in check.get("assertions", {}).items():
                    assertions.add(Assertion(type=target.split(":")[0], permission=permission, expected=expected))
    written = {RelationKey(type=item["object"].split(":")[0], relation=item["relation"]) for item in tuples}
    return ModelTests(assertions=frozenset(assertions), written=frozenset(written))


def _compare(table: str, actual: Mapping[str, object], allowed: Mapping[str, object], meaning: str) -> list[str]:
    problems = []
    for name in sorted(set(actual) | set(allowed)):
        if actual.get(name) != allowed.get(name):
            problems.append(
                f"limits.toml [{table}] {name}: the model has {_show(actual.get(name))} {meaning}, "
                f"the limit says {_show(allowed.get(name))}. Change the model, or agree the new limit in review."
            )
    return problems


def _show(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, frozenset):
        return ", ".join(sorted(value))
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="write model.fga from products/authz/model/")
    build.add_argument("--force", action="store_true", help="overwrite changes made to model.fga by hand")
    commands.add_parser("check", help="check model.fga and openfga_model.json against the model rules")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            ModelBuilder().write(force=args.force)
            return 0
        problems = ModelRules.load().problems()
    except ModelSourceError as error:
        problems = [str(error)]
    for problem in problems:
        sys.stderr.write(f"{problem}\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
