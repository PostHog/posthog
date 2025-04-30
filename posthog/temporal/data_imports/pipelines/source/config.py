import dataclasses
import typing

_T = typing.TypeVar("_T")


def _noop_convert(x: typing.Any) -> typing.Any:
    return x


@dataclasses.dataclass
class MetaConfiguration:
    """Class used to store metadata used for config."""

    prefix: str | None = None
    lookup_name: str | None = None
    converter: typing.Callable[[typing.Any], typing.Any] = _noop_convert


class ConfigInstance(typing.Protocol):
    __dataclass_fields__: typing.ClassVar[dict[str, dataclasses.Field[typing.Any]]]
    __source_config_meta: typing.ClassVar[MetaConfiguration]

    @classmethod
    def from_dict(cls, d: dict[str, typing.Any]) -> typing.Self: ...


_ConfigT = typing.TypeVar("_ConfigT", bound="ConfigInstance")


META_KEY = "_SOURCE_CONFIG_META"


def to_config(
    config_cls: type[_ConfigT], d: dict[str, typing.Any], prefixes: tuple[str, ...] | None = None
) -> _ConfigT:
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
    inputs = {}
    top_level_prefixes = prefixes or ()

    try:
        fields = dataclasses.fields(config_cls)
    except TypeError:
        # We raise our own to indicate that you should use @config.
        raise TypeError("must be called with a config type or instance")

    for field in fields:
        if isinstance(field.type, str):
            field_type = _lookup_type(field.type, locals(), globals())  # type: ignore
        else:
            field_type = field.type

        try:
            field_type_metadata: MetaConfiguration | None = field_type.__source_config_meta
        except AttributeError:
            field_type_metadata = None

        field_metadata = field.metadata.get(META_KEY, None)

        if field_type_metadata:
            # We are dealing with a nested config
            if field.name in d:
                # Assuming a nested structure, so we don't need prefixes
                value = to_config(field_type, d[field.name], prefixes)

            else:
                # Assuming a flat structure, so we need to resolve prefixes for
                # nested config.
                nested_prefix = field_type_metadata.prefix

                if field_metadata and field_metadata.prefix is not None:
                    # Prefer attribute-level prefix if set
                    nested_prefixes = (*top_level_prefixes, field_metadata.prefix)
                elif nested_prefix:
                    # Prefer the class-level prefix if set
                    nested_prefixes = (*top_level_prefixes, nested_prefix)
                else:
                    default_nested_prefix = _get_default_prefix_for_class(field_type)
                    nested_prefixes = (*top_level_prefixes, default_nested_prefix)

                value = to_config(field_type, d, nested_prefixes)

        else:
            key = _get_key(field, top_level_prefixes)

            try:
                value = d[key]
            except KeyError:
                continue

        if field_metadata and field_metadata.converter:
            convert = field_metadata.converter
        else:
            convert = _noop_convert

        inputs[field.name] = convert(value)

    return config_cls(**inputs)


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


def _get_key(field: dataclasses.Field[typing.Any], prefixes: tuple[str, ...]) -> str:
    """Get the key used to lookup a field."""
    try:
        metadata = field.metadata[META_KEY]
    except KeyError:
        return "_".join((*prefixes, field.name))

    name = field.name
    if metadata.lookup_name is not None:
        name = metadata.lookup_name

    prefixes = prefixes
    if metadata.prefix is not None:
        prefixes = metadata.prefix

    return "_".join((*prefixes, name))


def _get_default_prefix_for_class(cls: type) -> str:
    """Get a default prefix for given class based on name.

    This function attempts to extract words from a class name to form a string
    with words separated by '_'.

    In this context, word has multiple exclusive definitions:
    * An uppercase character followed by a sequence of lowercase characters.
    * A sequence of uppercase characters.

    These are only heuristics though and there are cases in which we cannot
    separate words, like if a class name is composed of multiple continuous
    uppercase characters, e.g. "AWSKMSKey" would result in "awskms_key" instead
    of perhaps the expected "aws_kms_key".

    Examples:
        >>> class SSHTunnel: ...
        >>> _get_default_prefix_for_class(SSHTunnel)
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
    lookup_name: str | None = None,
    converter: typing.Callable[[typing.Any], typing.Any] = _noop_convert,
) -> _T:
    """Wrapper for config fields to enable additional functionality."""
    metadata = {META_KEY: MetaConfiguration(prefix=prefix, lookup_name=lookup_name, converter=converter)}

    if default:
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
def config(
    maybe_cls: None = ..., *, prefix: str | None = None
) -> typing.Callable[[type[_T]], type[ConfigInstance]]: ...


@typing.overload
@typing.dataclass_transform()
def config(maybe_cls: type[_T], *, prefix: str | None = None) -> type[ConfigInstance]: ...


@typing.dataclass_transform()
def config(
    maybe_cls: type[_T] | None = None, *, prefix: str | None = None
) -> type[ConfigInstance] | typing.Callable[[type[_T]], type[ConfigInstance]]:
    """Wrap a class to mark it as a config.

    A config class will include a `from_dict` `classmethod` to initialize
    the config from a dictionary.

    Arguments:
        prefix: Optionally override the default prefix for this class.
    """

    def wrap(cls: type[_T]) -> type[ConfigInstance]:
        def from_dict(cls: type[ConfigInstance], d: dict[str, typing.Any]) -> ConfigInstance:
            if prefix:
                prefixes = (prefix,)
            else:
                prefixes = None

            return to_config(cls, d, prefixes=prefixes)

        new_cls = typing.cast(type[ConfigInstance], cls)

        new_cls.from_dict = classmethod(from_dict)  # type: ignore
        new_cls.__source_config_meta = MetaConfiguration(prefix=prefix)

        return dataclasses.dataclass(new_cls)

    if maybe_cls is not None:
        return wrap(maybe_cls)

    return wrap


def str_to_bool(s: str | bool) -> bool:
    """A converter to return a bool from a str."""
    if isinstance(s, bool):
        return s

    return s.lower() in {"true", "yes", "1"}
