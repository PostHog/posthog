from posthog.temporal.data_imports.pipelines.source import config


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

    assert cfg.b.a.a == "test"
    assert cfg.b.a.b == 1
    assert cfg.b.a.c == "something"

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
