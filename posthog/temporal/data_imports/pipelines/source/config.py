import dataclasses
import types
import typing

META_KEY = "_SOURCE_CONFIG_META"

_T = typing.TypeVar("_T")


class _Dataclass(typing.Protocol):
    __dataclass_fields__: typing.ClassVar[dict[str, typing.Any]]


class Config(_Dataclass, typing.Protocol):
    """Protocol for config dataclasses.

    Unfortunately, we cannot convince type checkers that the classes we decorate
    include additional synthesized methods (i.e. `from_dict`). So, if you use
    any of the methods, add this protocol to your config's parent classes as a
    way to tell type checkers everything is fine.

    Finally, a `Config` is also a dataclass, which is useful if you are going to
    keep passing this around.

    Examples:
        This works but mypy and other type checkers will complain:

        >>> @config
        ... class MyConfig: pass
        >>> MyConfig.from_dict({})
        MyConfig()

        Subclass from this protocol as an offering to the type gods:

        >>> @config
        ... class MyConfig(Config): pass
        >>> MyConfig.from_dict({})
        MyConfig()

        Obviously, you can also tell them to shut up with a type: ignore
        comment.
    """

    @classmethod
    def from_dict(cls: type[_T], d: dict[str, typing.Any]) -> _T: ...


def _noop_convert(x: typing.Any) -> typing.Any:
    """No-op function used as a default converter."""
    return x


@dataclasses.dataclass
class MetaConfig:
    """Class used to store metadata used for config."""

    prefix: str | None = None
    alias: str | None = None
    converter: typing.Callable[[typing.Any], typing.Any] = _noop_convert


def to_config(config_cls: type[Config], d: dict[str, typing.Any], prefixes: tuple[str, ...] | None = None) -> Config:
    """Initialize a class from dict.

    This function recursively initializes any nested classes.

    Arguments:
        config_cls: The class we are initializing. Must be decorated with @config.
        d: The dictionary we are using to initialize the class.
        prefixes: Used in recursive call, should be left empty by top level
            callers.

    Raises:
        TypeError: If called with a class not decorated with @config.
    """
    if not is_config(config_cls):
        # Similar to exception raised by dataclass, but we raise our own
        # to indicate that you should use @config.
        raise TypeError("must be called with a config type or instance")

    top_level_prefixes = prefixes or ()
    inputs = {}

    fields = dataclasses.fields(config_cls)

    for field in fields:
        field_type = _resolve_field_type(field)
        field_meta = field.metadata.get(META_KEY, None)

        field_flat_key = _get_flat_key(field, prefixes or ())
        field_nested_key = _get_nested_key(field)

        if field_nested_key in d:
            field_key = field_nested_key
        else:
            field_key = field_flat_key

        if field_meta and field_meta.converter:
            convert = field_meta.converter
        else:
            convert = _noop_convert

        if is_config(field.type) or _is_union_of_config(field.type):
            # We are dealing with a nested config, which could be part of a union
            config_types = typing.get_args(field.type) or (field_type,)

            for config_type in config_types:
                if not is_config(config_type):
                    try:
                        value = d[field_key]
                    except KeyError:
                        continue
                    else:
                        inputs[field.name] = convert(value)
                        break

                field_type_meta: MetaConfig | None = _try_get_meta(config_type)
                # We have checked that this is a config, so meta attribute must
                # be set
                assert field_type_meta

                if field_nested_key in d:
                    try:
                        value = to_config(config_type, d[field_nested_key], prefixes)
                    except TypeError:
                        # We want to try all possible config types
                        continue
                    else:
                        inputs[field.name] = convert(value)
                        break

                else:
                    # Assuming a flat structure
                    field_prefixes = _resolve_field_prefixes(
                        field_type, field_type_meta, field_meta, top_level_prefixes
                    )

                    try:
                        value = to_config(field_type, d, field_prefixes)
                    except TypeError:
                        # We want to try all possible config types
                        continue
                    else:
                        inputs[field.name] = convert(value)
                        break

        else:
            try:
                value = d[field_key]
            except KeyError:
                continue
            else:
                inputs[field.name] = convert(value)

    return config_cls(**inputs)


def _resolve_field_type(field: dataclasses.Field[typing.Any]) -> type:
    """Resolve a field's type."""
    if isinstance(field.type, str):
        field_type = _lookup_type(field.type, locals(), globals())  # type: ignore
    else:
        field_type = field.type

    return field_type


def _lookup_type(type_to_resolve: str, locals: dict[str, typing.Any], globals: dict[str, typing.Any]) -> type:
    """Lookup a type in provided locals and globals.

    Used to resolve any type hints that are strings.
    """
    try:
        return locals[type_to_resolve]
    except KeyError:
        try:
            return globals[type_to_resolve]
        except KeyError:
            raise TypeError(f"Unknown type: '{type_to_resolve}'")


def _try_get_meta(t: type) -> MetaConfig | None:
    """Attempt to get metadata from config type."""
    try:
        field_type_meta: MetaConfig | None = t.__source_config_meta  # type: ignore
    except AttributeError:
        field_type_meta = None
    return field_type_meta


def _is_union_of_config(t: typing.Any) -> bool:
    """Check if given type is a union consisting of at least one config."""
    origin = typing.get_origin(t)
    return (origin is typing.Union or origin is types.UnionType) and any(is_config(arg) for arg in typing.get_args(t))


def is_config(maybe_config: typing.Any):
    """Check meta attribute to identify config classes."""
    return hasattr(maybe_config, "__source_config_meta")


def _resolve_field_prefixes(
    t: type, cls_meta: MetaConfig, field_meta: MetaConfig | None, top_level_prefixes: tuple[str, ...]
):
    """Resolve a prefix to use when field is stored in flat dictionary."""
    field_prefix = cls_meta.prefix

    if field_meta and field_meta.prefix is not None:
        # Prefer attribute-level prefix if set
        field_prefixes = (*top_level_prefixes, field_meta.prefix)
    elif field_prefix:
        # Prefer the class-level prefix if set
        field_prefixes = (*top_level_prefixes, field_prefix)
    else:
        default_field_prefix = _get_default_prefix_for_class(t)
        field_prefixes = (*top_level_prefixes, default_field_prefix)

    return field_prefixes


def _get_flat_key(field: dataclasses.Field[typing.Any], prefixes: tuple[str, ...]) -> str:
    """Get the key used to lookup a field in a flat dictionary."""
    try:
        config_meta = field.metadata[META_KEY]
    except KeyError:
        return "_".join((*prefixes, field.name))

    name = field.name
    if config_meta.alias is not None:
        name = config_meta.alias

    if config_meta.prefix is not None:
        prefixes = (config_meta.prefix,)

    return "_".join((*prefixes, name))


def _get_nested_key(field: dataclasses.Field[typing.Any]) -> str:
    """Get the key used to lookup a field in a nested dictionary."""
    name = field.name

    try:
        config_meta = field.metadata[META_KEY]
    except KeyError:
        return name

    if config_meta.alias is not None:
        name = config_meta.alias

    return name


def _get_default_prefix_for_class(cls: type) -> str:
    """Get a default prefix for given class based on name.

    This function attempts to extract words from a class name to form a string
    with words separated by '_'.

    In this context, word has multiple exclusive definitions:
    * An uppercase character followed by a sequence of lowercase characters.
    * A sequence of uppercase characters.

    Moreover, continuing with the heuristics, we exclude the string
    "config" from the default prefix if it's the final component, unless it is
    the only string in the class name.

    These are only heuristics though and there are cases in which we cannot
    separate words, like if a class name is composed of multiple continuous
    uppercase characters, e.g. "AWSKMSKey" would result in "awskms_key" instead
    of perhaps the expected "aws_kms_key".

    Examples:
        >>> class SSHTunnel: ...
        >>> _get_default_prefix_for_class(SSHTunnel)
        'ssh_tunnel'
        >>> class SSHTunnelConfig: ...
        >>> _get_default_prefix_for_class(SSHTunnelConfig)
        'ssh_tunnel'
        >>> class Test: ...
        >>> _get_default_prefix_for_class(Test)
        'test'
        >>> class MyClass: ...
        >>> _get_default_prefix_for_class(MyClass)
        'my_class'
        >>> class AWSKMSKey: ...
        >>> _get_default_prefix_for_class(AWSKMSKey)
        'awskms_key'
        >>> class Config: ...
        >>> _get_default_prefix_for_class(Config)
        'config'
    """
    cls_name = cls.__name__
    split = []
    current = ""

    for index, c in enumerate(cls_name):
        current += c.lower()

        try:
            next = cls_name[index + 1]
        except IndexError:
            split.append(current)
        else:
            if next.isupper() and c.islower():
                # Going from lower to upper indicates new word starts with next char
                # and we should flush the current word.
                split.append(current)
                current = ""
            elif next.islower() and cls_name[: index + 1].isupper() and len(current) > 1:
                # We just finished with a sequence of uppercase characters and
                # we assume the last one we added was the start of the next word.
                split.append(current[:-1])
                current = current[-1]

    if len(split) > 1 and split[-1] == "config":
        split = split[:-1]

    return "_".join(split)


def value(
    *,
    default: _T | None = None,
    default_factory: typing.Callable[[], _T] | None = None,
    init: bool = True,
    repr: bool = True,
    hash: bool | None = None,
    compare: bool = True,
    kw_only: bool = False,
    prefix: str | None = None,
    alias: str | None = None,
    converter: typing.Callable[[typing.Any], typing.Any] = _noop_convert,
) -> _T:
    """Wrapper for config values to enable additional functionality.

    Usage is similar to `dataclasses.field` and all its arguments are supported,
    except for `metadata` which we manage here to enable additional
    functionality.

    Following arguments description will omit arguments that are simply passed
    along to `dataclasses.field`

    Arguments:
        prefix: Define a new prefix to lookup this value in a mapping.
        alias: Set a new lookup alias for this value in a mapping.
        converter: A function to convert the value obtained from the mapping.
    """
    metadata = {META_KEY: MetaConfig(prefix=prefix, alias=alias, converter=converter)}

    if default is not None:
        return dataclasses.field(
            default=default,
            hash=hash,
            compare=compare,
            init=init,
            repr=repr,
            kw_only=kw_only,
            metadata=metadata,
        )
    elif default_factory:
        return dataclasses.field(
            default_factory=default_factory,
            hash=hash,
            compare=compare,
            init=init,
            repr=repr,
            kw_only=kw_only,
            metadata=metadata,
        )
    else:
        return dataclasses.field(
            hash=hash,
            compare=compare,
            init=init,
            repr=repr,
            kw_only=kw_only,
            metadata=metadata,
        )


@typing.overload
@typing.dataclass_transform()
def config(maybe_cls: None = ..., *, prefix: str | None = None) -> typing.Callable[[type[_T]], type[_T]]: ...


@typing.overload
@typing.dataclass_transform()
def config(maybe_cls: type[_T], *, prefix: str | None = None) -> type[_T]: ...


def config(
    maybe_cls: type[_T] | None = None, *, prefix: str | None = None
) -> type[_T] | typing.Callable[[type[_T]], type[_T]]:
    """Wrap a class to mark it as a config.

    A config class will include a `from_dict` `classmethod` to initialize
    the config from a dictionary.

    Arguments:
        prefix: Optionally override the default prefix for this class.
    """

    def wrap(cls: type[_T]) -> type[_T]:
        def from_dict(cls, d: dict[str, typing.Any]):
            if prefix:
                prefixes = (prefix,)
            else:
                prefixes = None

            return to_config(cls, d, prefixes=prefixes)

        cls = dataclasses.dataclass(cls)
        setattr(cls, "from_dict", classmethod(from_dict))  # noqa: B010
        setattr(cls, "__source_config_meta", MetaConfig(prefix=prefix))  # noqa: B010

        return cls

    if maybe_cls is not None:
        return wrap(maybe_cls)

    return wrap


def str_to_bool(s: str | bool) -> bool:
    """A converter to return a bool from a str."""
    if isinstance(s, bool):
        return s

    return s.lower() in {"true", "yes", "1"}
