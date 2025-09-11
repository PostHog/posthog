import typing

from posthog.temporal.data_imports.sources.common import config


def test_empty_config():
    """Test `config.to_config` with an empty class."""

    @config.config
    class TestConfig(config.Config):
        pass

    cfg = TestConfig.from_dict({})
    assert cfg


def test_basic_to_config():
    """Test `config.to_config` with a basic class."""

    @config.config
    class TestConfig(config.Config):
        a: str
        b: int = 0
        c: str | None = None

    config_dict = {
        "a": "test",
        "c": "present",
    }

    cfg = TestConfig.from_dict(config_dict)

    assert cfg.a == "test"
    assert cfg.b == 0
    assert cfg.c == "present"


def test_basic_to_config_converters():
    """Test `config.to_config` can convert using converters."""

    @config.config
    class TestConfig(config.Config):
        a: int = config.value(converter=int)
        b: bool = config.value(converter=config.str_to_bool)
        c: bool = config.value(converter=config.str_to_bool)

    config_dict = {
        "a": "123",
        "b": "True",
        "c": "false",
    }

    cfg = TestConfig.from_dict(config_dict)

    assert cfg.a == 123
    assert cfg.b is True
    assert cfg.c is False


def test_nested_to_config_with_flat_dict():
    """Test `config.to_config` with a nested set of classes.

    We test parsing a configuration from a flat dictionary while overriding
    prefixes used for each attribute.
    """

    @config.config
    class TestConfigA:
        a: str
        b: int = 0
        c: str | None = None

    @config.config
    class TestConfigB:
        a: TestConfigA = config.value(prefix="a")

    @config.config
    class TestConfigC(config.Config):
        a: TestConfigA = config.value(prefix="a")
        b: TestConfigB = config.value(prefix="b")
        d: bool = False

    config_dict = {
        "a_a": "test",
        "b_a_a": "test",
        "b_a_b": 1,
        "b_a_c": "something",
        "d": True,
    }

    cfg = TestConfigC.from_dict(config_dict)

    assert cfg.a.a == "test"
    assert cfg.a.b == 0
    assert cfg.a.c is None

    assert cfg.b.a.a == "test"
    assert cfg.b.a.b == 1
    assert cfg.b.a.c == "something"

    assert cfg.d is True


def test_nested_to_config_with_nested_dict():
    """Test `config.to_config` with a nested set of classes.

    We test parsing a configuration from a nested dictionary.
    """

    @config.config
    class TestConfigA:
        a: str
        b: int = 0
        c: str | None = None

    @config.config
    class TestConfigB:
        a: TestConfigA

    @config.config
    class TestConfigC(config.Config):
        a: TestConfigA
        b: TestConfigB
        d: bool = False

    config_dict = {
        "a": {
            "a": "test",
        },
        "b": {
            "a": {
                "a": "test",
                "b": 1,
                "c": "something",
            }
        },
        "d": True,
    }

    cfg = TestConfigC.from_dict(config_dict)

    assert cfg.a.a == "test"
    assert cfg.a.b == 0
    assert cfg.a.c is None

    assert cfg.b.a.a == "test"
    assert cfg.b.a.b == 1
    assert cfg.b.a.c == "something"

    assert cfg.d is True


def test_nested_to_config_with_flat_dict_default_prefix():
    """Test `config.to_config` with a nested set of classes.

    We are particularly interested in the mechanism to resolve default prefixes.
    Each class name should automatically resolve to a prefix that matches our
    flat dictionary.
    """

    @config.config
    class A:
        a: str
        b: int = 0
        c: str | None = None

    @config.config
    class B:
        a: A

    @config.config
    class C(config.Config):
        a: A
        b: B
        d: bool = False

    config_dict = {
        "a_a": "test",
        "b_a_a": "test",
        "b_a_b": 1,
        "b_a_c": "something",
        "d": True,
    }

    cfg = C.from_dict(config_dict)

    assert cfg.a.a == "test"
    assert cfg.a.b == 0
    assert cfg.a.c is None
    assert isinstance(cfg.a, A)

    assert cfg.b.a.a == "test"
    assert cfg.b.a.b == 1
    assert cfg.b.a.c == "something"
    assert isinstance(cfg.b, B)
    assert isinstance(cfg.b.a, A)

    assert cfg.d is True


def test_to_config_override_alias():
    """Test `config.to_config` with overriden lookup names.

    Lookup names in the flat dictionary can be specified when using
    `config.value`.
    """

    @config.config
    class TestConfig(config.Config):
        a: str = config.value(alias="not_a")
        b: int = config.value(alias="not_b")
        c: str | None = config.value(alias="not_c")

    config_dict = {
        "not_a": "test",
        "not_b": 10,
        "not_c": "seen",
        "c": "not-seen",
    }

    cfg = TestConfig.from_dict(config_dict)

    assert cfg.a == "test"
    assert cfg.b == 10
    assert cfg.c == "seen"


def test_to_config_override_alias_fallback():
    """Test `config.to_config` with overriden lookup names but
    fallback to the original name if the alias key os missing.

    Lookup names in the flat dictionary can be specified when using
    `config.value`.
    """

    @config.config
    class TestConfig(config.Config):
        a: str = config.value(alias="not_a")
        b: int = config.value(alias="not_b")
        c: str | None = config.value(alias="not_c")

    config_dict = {
        "a": "test",
        "b": 10,
        "not_c": "seen",
        "c": "not-seen",
    }

    cfg = TestConfig.from_dict(config_dict)

    assert cfg.a == "test"
    assert cfg.b == 10
    assert cfg.c == "seen"


def test_to_config_union_nested_configs():
    """Test `config.to_config` with a union of nested configs."""

    @config.config
    class A:
        a: str

    @config.config
    class B:
        b: int

    @config.config
    class C(config.Config):
        inner: A | B | int

    config_dict: dict[str, typing.Any] = {"inner": {"b": 1}}

    b_cfg = C.from_dict(config_dict)

    assert isinstance(b_cfg.inner, B)
    assert b_cfg.inner.b == 1

    config_dict = {"inner": {"a": "test"}}

    a_cfg = C.from_dict(config_dict)

    assert isinstance(a_cfg.inner, A)
    assert a_cfg.inner.a == "test"

    config_dict = {"inner": 2}

    a_cfg = C.from_dict(config_dict)

    assert isinstance(a_cfg.inner, int)
    assert a_cfg.inner == 2


def test_to_config_union_nested_configs_with_alias():
    """Test `config.to_config` with a union of nested configs using alias."""

    @config.config
    class A:
        a: str

    @config.config
    class B:
        b: int

    @config.config
    class C(config.Config):
        inner: A | B = config.value(alias="some")

    config_dict: dict[str, typing.Any] = {"some": {"b": 1}}

    b_cfg = C.from_dict(config_dict)

    assert isinstance(b_cfg.inner, B)
    assert b_cfg.inner.b == 1

    config_dict = {"some": {"a": "test"}}

    a_cfg = C.from_dict(config_dict)

    assert isinstance(a_cfg.inner, A)
    assert a_cfg.inner.a == "test"


def test_validate_dict():
    @config.config
    class TestConfig(config.Config):
        a: str

    config_dict = {
        "b": "test",
    }

    is_valid, errors = TestConfig.validate_dict(config_dict)

    assert is_valid is False
    assert len(errors) == 1

    config_dict = {
        "a": "test",
    }

    is_valid, errors = TestConfig.validate_dict(config_dict)

    assert is_valid is True
    assert len(errors) == 0


def test_validate_dict_alias():
    @config.config
    class TestConfig(config.Config):
        a: str = config.value(alias="c")

    config_dict = {
        "b": "test",
    }

    is_valid, errors = TestConfig.validate_dict(config_dict)

    assert is_valid is False
    assert len(errors) == 1

    config_dict = {
        "c": "test",
    }

    is_valid, errors = TestConfig.validate_dict(config_dict)

    assert is_valid is True
    assert len(errors) == 0


def test_validate_dict_default():
    @config.config
    class TestConfig(config.Config):
        a: str = config.value(default="1")

    config_dict = {
        "b": "test",
    }

    is_valid, errors = TestConfig.validate_dict(config_dict)

    assert is_valid is True
    assert len(errors) == 0


def test_validate_dict_with_nested_dict():
    @config.config
    class TestConfigA:
        a: str
        b: int = 0
        c: str | None = None

    @config.config
    class TestConfigB:
        a: TestConfigA

    @config.config
    class TestConfigC(config.Config):
        a: TestConfigA
        b: TestConfigB
        d: bool = False

    config_dict = {
        "a": {
            "a": "test",
        },
        "b": {
            "a": {
                "a": "test",
                "b": 1,
                "c": "something",
            }
        },
        "d": True,
    }

    is_valid, errors = TestConfigC.validate_dict(config_dict)

    assert is_valid is True
    assert len(errors) == 0

    config_dict = {
        "a": {
            "non_existent_key": "test",
        },
        "b": {
            "a": {
                "a": "test",
                "b": 1,
                "c": "something",
            }
        },
        "d": True,
    }

    is_valid, errors = TestConfigC.validate_dict(config_dict)

    assert is_valid is False
    assert len(errors) == 1
