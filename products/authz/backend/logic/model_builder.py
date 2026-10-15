"""Build the OpenFGA model from products/authz/model/ and check it against the model rules.

Run products/authz/generate_model.sh rather than this module. The script also converts the model to JSON and runs the
model tests.
"""

import re
import sys
import json
import hashlib
import argparse
from collections.abc import Mapping
from functools import cached_property
from pathlib import Path
from typing import Literal, TypedDict

import yaml

from posthog.dataclasses import frozen

from products.authz.backend.facade.enums import Action, Level, ResourceType

PRODUCT_DIR = Path(__file__).resolve().parents[2]
SOURCE_DIR = PRODUCT_DIR / "model"
GENERATED_DIR = PRODUCT_DIR / "generated"
MODEL_PATH = GENERATED_DIR / "model.fga"
JSON_MODEL_PATH = GENERATED_DIR / "openfga_model.json"

CORE_FILE = "core.fga"
BASES_FILE = "object.fga"
RESOURCES_DIR = "resources"
TESTS_SUFFIX = ".fga.yaml"
CORE_TESTS = "core"
PERMISSION_PREFIX = "can_"
BANNER = "# Generated from products/authz/model/ by products/authz/generate_model.sh. Do not edit."
DIGEST_PREFIX = "# Content digest: "
TYPE_PATTERN = re.compile(r"^type (\w+)(?: extends (\w+))?\s*$")
STATEMENT_PATTERN = re.compile(r"^\s+(define|override) (\w+):\s*(.+?)\s*$")
REMOVE_PATTERN = re.compile(r"^\s+remove (\w+)\s*$")
DEFINE_PATTERN = re.compile(r"^\s+define (\w+):\s*(.+?)\s*$")
RESTRICTION_PATTERN = re.compile(r"\[([^\]]*)\]")
FROM_PATTERN = re.compile(r"(\w+) from (\w+)")
IDENTIFIER_PATTERN = re.compile(r"[a-z_][a-z0-9_]*")
OPERATOR_WORDS = frozenset({"or", "and", "but", "not", "from"})


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
class Statement:
    kind: Literal["define", "override", "remove"]
    name: str
    definition: str
    comments: tuple[str, ...]


@frozen
class ExtendedType:
    """A type from a base or resource file, before its base is applied."""

    name: str
    base: str | None
    statements: tuple[Statement, ...]


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
    """What one test file covers: the permission results it checks and the relations its tuples write."""

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


def parse_extended_types(text: str, source: str) -> tuple[ExtendedType, ...]:
    """Parse a base or resource file: OpenFGA types plus `extends`, `override` and `remove`."""
    types: list[ExtendedType] = []
    name: str | None = None
    base: str | None = None
    statements: list[Statement] = []
    comments: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            comments.append(stripped.removeprefix("#").strip())
            continue
        if match := TYPE_PATTERN.match(line):
            if name is not None:
                types.append(ExtendedType(name=name, base=base, statements=tuple(statements)))
            name, base = match.groups()
            statements, comments = [], []
        elif stripped == "relations" and name is not None:
            comments = []
        elif name is not None and (match := STATEMENT_PATTERN.match(line)):
            kind: Literal["define", "override"] = "define" if match.group(1) == "define" else "override"
            statements.append(
                Statement(kind=kind, name=match.group(2), definition=match.group(3), comments=tuple(comments))
            )
            comments = []
        elif name is not None and (match := REMOVE_PATTERN.match(line)):
            statements.append(Statement(kind="remove", name=match.group(1), definition="", comments=tuple(comments)))
            comments = []
        else:
            raise ModelSourceError(f"{source}:{number}: expected a type, define, override or remove line")
    if name is not None:
        types.append(ExtendedType(name=name, base=base, statements=tuple(statements)))
    return tuple(types)


def same_type_references(definition: str) -> set[str]:
    """Relation names on the same type that a definition reads, as bare names or as the tupleset of `x from y`."""
    expression = RESTRICTION_PATTERN.sub(" ", definition)
    references = {tupleset for _, tupleset in FROM_PATTERN.findall(expression)}
    expression = FROM_PATTERN.sub(" ", expression)
    references.update(word for word in IDENTIFIER_PATTERN.findall(expression) if word not in OPERATOR_WORDS)
    return references


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
        return (self.source_dir / CORE_FILE).read_text().strip()

    def core_types(self) -> tuple[TypeDefinition, ...]:
        return parse_types(self.core())

    def resource_files(self) -> tuple[Path, ...]:
        return tuple(sorted((self.source_dir / RESOURCES_DIR).glob("*.fga")))

    def bases(self) -> dict[str, TypeDefinition]:
        declared = {
            definition.name: definition
            for definition in parse_extended_types((self.source_dir / BASES_FILE).read_text(), BASES_FILE)
        }
        resolved: dict[str, TypeDefinition] = {}

        def resolve(name: str, chain: tuple[str, ...]) -> TypeDefinition:
            if name in resolved:
                return resolved[name]
            if name in chain:
                raise ModelSourceError(f"{BASES_FILE}: the bases {' -> '.join((*chain, name))} extend each other")
            if name not in declared:
                raise ModelSourceError(f"{BASES_FILE}: {chain[-1]} extends {name!r}, which is not a base")
            base = declared[name]
            parent = (
                TypeDefinition(name=name, relations=()) if base.base is None else resolve(base.base, (*chain, name))
            )
            resolved[name] = self.apply(parent, base, emit_comments=False)
            return resolved[name]

        for name in declared:
            resolve(name, ())
        return resolved

    def resources(self) -> tuple[TypeDefinition, ...]:
        bases = self.bases()
        taken = {definition.name for definition in self.core_types()} | set(bases)
        resources = []
        for path in self.resource_files():
            source = f"{RESOURCES_DIR}/{path.name}"
            types = parse_extended_types(path.read_text(), source)
            if len(types) != 1 or types[0].name != path.stem:
                raise ModelSourceError(f"{source}: a resource file holds one type, named {path.stem!r} after the file")
            resource = types[0]
            if resource.name in taken:
                raise ModelSourceError(f"{source}: {resource.name!r} is already a core type or a base")
            if resource.base is not None and resource.base not in bases:
                raise ModelSourceError(
                    f"{source}: {resource.name} must extend one of the bases in {BASES_FILE}: {', '.join(sorted(bases))}"
                )
            unexplained = [
                statement.name
                for statement in resource.statements
                if resource.base is not None and not statement.comments
            ]
            if unexplained:
                raise ModelSourceError(
                    f"{source}: add a comment above {', '.join(unexplained)} that says why {resource.name} needs it"
                )
            parent = (
                bases[resource.base] if resource.base is not None else TypeDefinition(name=resource.name, relations=())
            )
            resources.append(self.apply(parent, resource, emit_comments=True))
        return tuple(resources)

    def build(self) -> str:
        body = "\n\n".join([self.core(), *(render_type(resource) for resource in self.resources())]) + "\n"
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
    def apply(parent: TypeDefinition, extended: ExtendedType, *, emit_comments: bool) -> TypeDefinition:
        """Apply a type's statements to its base. Added permissions go last, other added relations before the permissions."""
        relations = list(parent.relations)
        removed = []
        for statement in extended.statements:
            label = f"{extended.name}.{statement.name}"
            names = {relation.name for relation in relations}
            is_permission = statement.name.startswith(PERMISSION_PREFIX)
            if statement.kind == "define":
                if statement.name in names:
                    raise ModelSourceError(f"{label}: {parent.name} already defines it. Use override, or another name.")
                relation = Relation(
                    name=statement.name,
                    definition=statement.definition,
                    comments=statement.comments if emit_comments else (),
                )
                position = next(
                    (index for index, existing in enumerate(relations) if existing.name.startswith(PERMISSION_PREFIX)),
                    len(relations),
                )
                relations.insert(len(relations) if is_permission else position, relation)
                continue
            if statement.name not in names:
                raise ModelSourceError(
                    f"{label}: {parent.name} does not define it, so there is nothing to {statement.kind}."
                )
            if not is_permission:
                raise ModelSourceError(
                    f"{label}: a type can {statement.kind} only permissions (can_*). "
                    f"Stored relations and access levels stay as {parent.name} defines them."
                )
            if statement.kind == "override":
                relations = [
                    Relation(
                        name=statement.name,
                        definition=statement.definition,
                        comments=statement.comments if emit_comments else (),
                    )
                    if existing.name == statement.name
                    else existing
                    for existing in relations
                ]
            else:
                relations = [existing for existing in relations if existing.name != statement.name]
                removed.append(statement.name)
        for name in removed:
            users = [relation.name for relation in relations if name in same_type_references(relation.definition)]
            if users:
                raise ModelSourceError(
                    f"{extended.name}.{name}: {', '.join(users)} still uses it, so it cannot be removed."
                )
        return TypeDefinition(name=extended.name, relations=tuple(relations))

    @staticmethod
    def _is_unedited_output(model: str) -> bool:
        banner, _, rest = model.partition("\n")
        digest_line, _, body = rest.partition("\n")
        return banner == BANNER and digest_line == f"{DIGEST_PREFIX}{content_digest(body)}"


class ModelRules:
    """The rules that keep the model consistent with the SDK and covered by tests."""

    def __init__(
        self,
        *,
        model: str,
        builder: ModelBuilder,
        json_relations: Mapping[str, frozenset[str]],
        tests: Mapping[str, ModelTests],
    ) -> None:
        self.model = model
        self.builder = builder
        self.json_relations = json_relations
        self.tests = tests
        self.types = {definition.name: definition for definition in parse_types(model)}

    @cached_property
    def resource_names(self) -> frozenset[str]:
        return frozenset(path.stem for path in self.builder.resource_files())

    @classmethod
    def load(cls) -> "ModelRules":
        builder = ModelBuilder()
        return cls(
            model=MODEL_PATH.read_text(),
            builder=builder,
            json_relations=relations_from_json(json.loads(JSON_MODEL_PATH.read_text())),
            tests=read_test_files(builder),
        )

    def problems(self) -> list[str]:
        try:
            built = self.builder.build()
        except ModelSourceError as error:
            return [str(error)]
        if self.model != built:
            return ["generated/model.fga does not match its sources. Run products/authz/generate_model.sh."]
        return [
            *self._json_matches_model(),
            *self._resources_are_resource_types(),
            *self._resource_permissions_map_to_actions(),
            *self._relations_reach_a_permission(),
            *self._types_are_tested(),
        ]

    def _json_matches_model(self) -> list[str]:
        model_types = {name: definition.relation_names() for name, definition in self.types.items()}
        if dict(self.json_relations) != model_types:
            return [
                "generated/openfga_model.json does not match generated/model.fga. Run products/authz/generate_model.sh."
            ]
        return []

    def _resources_are_resource_types(self) -> list[str]:
        known = {resource_type.value for resource_type in ResourceType}
        return [
            f"{RESOURCES_DIR}/{name}.fga: {name!r} is not a ResourceType value in products/authz/backend/facade/enums.py."
            for name in sorted(self.resource_names - known)
        ]

    def _resource_permissions_map_to_actions(self) -> list[str]:
        actions = {action.value for action in Action}
        return [
            f"{name}.{relation.name}: there is no SDK Action {relation.name.removeprefix(PERMISSION_PREFIX)!r}, "
            f"so app code cannot check this permission. Add the Action, or use an existing permission name."
            for name in sorted(self.resource_names)
            for relation in self.types[name].relations
            if relation.name.startswith(PERMISSION_PREFIX)
            and relation.name.removeprefix(PERMISSION_PREFIX) not in actions
        ]

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
        references = [RelationKey(type=key.type, relation=name) for name in same_type_references(definition)]
        for restriction in RESTRICTION_PATTERN.findall(definition):
            for item in restriction.split(","):
                subject = item.split(" with ")[0].strip()
                if "#" in subject:
                    subject_type, relation = subject.split("#")
                    references.append(RelationKey(type=subject_type, relation=relation))
        for target, tupleset in FROM_PATTERN.findall(RESTRICTION_PATTERN.sub(" ", definition)):
            parents = RESTRICTION_PATTERN.findall(definitions.get(RelationKey(type=key.type, relation=tupleset), ""))
            for parent in (item.split(" with ")[0].strip() for group in parents for item in group.split(",")):
                references.append(RelationKey(type=parent.split("#")[0].split(":")[0], relation=target))
        return references

    def _types_are_tested(self) -> list[str]:
        problems = []
        for name, definition in self.types.items():
            owner = name if name in self.resource_names else CORE_TESTS
            test_file = owner_test_file(owner)
            tests = self.tests.get(owner)
            if tests is None:
                problems.append(f"{test_file} is missing. Add the tests for {name}.")
                continue
            for relation in definition.relations:
                if relation.name.startswith(PERMISSION_PREFIX):
                    problems.extend(
                        f"{name}.{relation.name}: {test_file} has no check that expects {str(expected).lower()}. Add one."
                        for expected in (True, False)
                        if Assertion(type=name, permission=relation.name, expected=expected) not in tests.assertions
                    )
                if "[" in relation.definition and RelationKey(type=name, relation=relation.name) not in tests.written:
                    problems.append(
                        f"{name}.{relation.name}: no tuple in {test_file} writes this relation. Add a test that uses it."
                    )
        return problems


def owner_test_file(owner: str) -> str:
    return f"{CORE_TESTS}{TESTS_SUFFIX}" if owner == CORE_TESTS else f"{RESOURCES_DIR}/{owner}{TESTS_SUFFIX}"


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
    tuple_files: list[str]
    tuples: list[_TestTuple]
    tests: list[_TestCase]


def read_test_files(builder: ModelBuilder) -> dict[str, ModelTests]:
    owners = [CORE_TESTS, *(path.stem for path in builder.resource_files())]
    paths = {owner: builder.source_dir / owner_test_file(owner) for owner in owners}
    return {owner: read_model_tests(path) for owner, path in paths.items() if path.exists()}


def read_model_tests(path: Path) -> ModelTests:
    tests: _TestFile = yaml.safe_load(path.read_text())
    tuples = list(tests.get("tuples", []))
    for tuple_file in tests.get("tuple_files", []):
        tuples.extend(yaml.safe_load((path.parent / tuple_file).read_text()) or [])
    assertions = set()
    for test in tests.get("tests", []):
        tuples.extend(test.get("tuples", []))
        for check in test.get("check", []):
            targets = check.get("objects") or [check.get("object", "")]
            for target in targets:
                for permission, expected in check.get("assertions", {}).items():
                    assertions.add(Assertion(type=target.split(":")[0], permission=permission, expected=expected))
    written = {RelationKey(type=item["object"].split(":")[0], relation=item["relation"]) for item in tuples}
    return ModelTests(assertions=frozenset(assertions), written=frozenset(written))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="write generated/model.fga from products/authz/model/")
    build.add_argument("--force", action="store_true", help="overwrite changes made to generated/model.fga by hand")
    commands.add_parser("check", help="check the generated model files against the model rules")
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
