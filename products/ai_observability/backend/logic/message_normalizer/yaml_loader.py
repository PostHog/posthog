import re

from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError, SafeConstructor
from ruamel.yaml.error import YAMLError

from .errors import RecipeCompileError

_YAML_1_2_CORE_INT = re.compile(r"[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+")


class _RecipeConstructor(SafeConstructor):
    # The frontend parser has no merge keys, so `<<` is an ordinary key that holds its value.
    def flatten_mapping(self, node):
        pass

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

    # ruamel writes both values into its duplicate-key message. A value built from nested aliases is shared in memory
    # but its text grows exponentially with the source, so the message names only the key.
    def check_mapping_key(self, node, key_node, mapping, key, value):
        if key in mapping:
            raise DuplicateKeyError(
                "while constructing a mapping", node.start_mark, f'found duplicate key "{key}"', key_node.start_mark
            )
        return True

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
    yaml.Constructor = _RecipeConstructor
    try:
        return yaml.load(source)
    # ruamel raises plain Python errors on some user input: ValueError for an oversized integer, TypeError for a list
    # used as a mapping key, LookupError for a malformed `!!bool` or `!!float` scalar, and AssertionError for a `%YAML`
    # version other than 1.1 or 1.2. A team recipe must only ever fail as a compile error.
    except (YAMLError, RecursionError, ValueError, TypeError, LookupError, AssertionError) as error:
        raise RecipeCompileError(f"Recipe YAML does not parse: {error}") from error
