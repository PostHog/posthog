import re
from typing import Final

from ruamel.yaml import YAML
from ruamel.yaml.composer import Composer, ComposerError
from ruamel.yaml.constructor import ConstructorError, DuplicateKeyError, SafeConstructor
from ruamel.yaml.error import YAMLError
from ruamel.yaml.events import AliasEvent
from ruamel.yaml.nodes import MappingNode
from ruamel.yaml.scanner import Scanner, ScannerError

from .errors import RecipeCompileError
from .values import key_text

_YAML_1_2_CORE_INT = re.compile(r"[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+")

MAX_FLOW_DEPTH: Final = 100


class _RecipeScanner(Scanner):
    # The scanner rechecks every open flow level on each token, so `[` nested a thousand deep costs seconds of CPU that
    # no deadline can interrupt. Recipes nest flow collections a few levels at most.
    def fetch_flow_collection_start(self, TokenClass, to_push):
        if self.flow_level >= MAX_FLOW_DEPTH:
            raise ScannerError(
                None, None, f"flow collections nest deeper than {MAX_FLOW_DEPTH} levels", self.reader.get_mark()
            )
        super().fetch_flow_collection_start(TokenClass, to_push)

    # A `%TAG` prefix is copied into every node that uses its handle, so one long prefix grows a short source the way an
    # alias would. Recipes use only the built-in `!` and `!!` handles.
    def scan_directive(self):
        token = super().scan_directive()
        if token.name == "TAG":
            raise ScannerError(None, None, "recipes do not support %TAG directives", token.start_mark)
        return token


class _RecipeComposer(Composer):
    # An alias reuses a node, so a short source can describe a tree exponentially larger than itself, and every later
    # pass over the recipe pays for that size. Rejecting anchors and aliases here, before any node is built, keeps the
    # loaded recipe linear in the length of its source.
    def compose_node(self, parent, index):
        event = self.parser.peek_event()
        if isinstance(event, AliasEvent) or event.anchor is not None:
            raise ComposerError(
                None, None, "recipes do not support YAML anchors (&name) or aliases (*name)", event.start_mark
            )
        return super().compose_node(parent, index)


class _RecipeConstructor(SafeConstructor):
    # The frontend parser rejects two keys only when their values are strictly equal, so `true:` and `1:` are two
    # fields there, while Python's `True == 1` would make them one duplicate. It then names each field by the key's
    # text, so `1:` and `"1":` are one field that holds the later value. The frontend parser also has no merge keys,
    # so `<<` is an ordinary key that holds its value.
    def construct_mapping(self, node, deep=False):
        if not isinstance(node, MappingNode):
            raise ConstructorError(None, None, f"expected a mapping node, but found {node.id}", node.start_mark)
        mapping: dict[str, object] = {}
        seen: set[tuple[bool, object]] = set()
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            identity = (isinstance(key, bool), tuple(key) if isinstance(key, list) else key)
            if identity in seen:
                raise DuplicateKeyError(
                    "while constructing a mapping", node.start_mark, f'found duplicate key "{key}"', key_node.start_mark
                )
            seen.add(identity)
            mapping[key_text(key)] = self.construct_object(value_node, deep=deep)
        return mapping

    # ruamel's resolver tags YAML 1.1 spellings (`1_000`, `0b11`, `-0x1`) as numbers. The frontend parser reads them
    # as text, so the constructor hands the text back unless the scalar is a YAML 1.2 core number.
    def construct_yaml_int(self, node):
        text = self.construct_scalar(node)
        if not _YAML_1_2_CORE_INT.fullmatch(text):
            return text
        if text.startswith(("0o", "0x")):
            value = int(text[2:], 8 if text[1] == "o" else 16)
            # Python reads hex and octal of any length, but writes no integer past its decimal digit limit as text, and
            # the compiler writes keys and values as JSON text. `str` raises here the ValueError that a decimal literal
            # of that length raises in `int`, so the recipe fails to load instead of failing later.
            str(value)
            return value
        return int(text)

    def construct_yaml_float(self, node):
        text = self.construct_scalar(node)
        return text if "_" in text else super().construct_yaml_float(node)


# The frontend parser keeps timestamps as plain strings, so a recipe reads the same text on both sides. Registering
# on a subclass leaves ruamel's shared SafeConstructor untouched for every other caller in the process.
_RecipeConstructor.add_constructor("tag:yaml.org,2002:timestamp", SafeConstructor.construct_yaml_str)
_RecipeConstructor.add_constructor("tag:yaml.org,2002:int", _RecipeConstructor.construct_yaml_int)
_RecipeConstructor.add_constructor("tag:yaml.org,2002:float", _RecipeConstructor.construct_yaml_float)
_RecipeConstructor.add_constructor("tag:yaml.org,2002:merge", SafeConstructor.construct_yaml_str)
_RecipeConstructor.add_constructor("tag:yaml.org,2002:value", SafeConstructor.construct_yaml_str)


def load_recipe_yaml(source: str) -> object:
    # Recipes are authored against the YAML 1.2 parser the frontend uses. PyYAML follows YAML 1.1, which reads
    # every rule's `on:` key as the boolean `True`. A YAML instance is not thread-safe, so each call builds one.
    yaml = YAML(typ="safe", pure=True)
    yaml.Scanner = _RecipeScanner
    yaml.Composer = _RecipeComposer
    yaml.Constructor = _RecipeConstructor
    try:
        return yaml.load(source)
    # ruamel raises plain Python errors on some user input: ValueError for an oversized integer, TypeError for a list
    # used as a mapping key, LookupError for a malformed `!!bool` or `!!float` scalar, and AssertionError for a `%YAML`
    # version other than 1.1 or 1.2. A team recipe must only ever fail as a compile error.
    except (YAMLError, RecursionError, ValueError, TypeError, LookupError, AssertionError) as error:
        raise RecipeCompileError(f"Recipe YAML does not parse: {error}") from error
