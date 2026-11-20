# posthog-typed-config

Typed config classes that parse a mapping of user input, such as the stored inputs of a data warehouse source.
The import name is `typed_config`.

The package is a leaf: it imports only the standard library, so any product can use it.
An import-linter contract in the root `pyproject.toml` keeps it that way.

## Usage

```python
import typed_config as config


@config.config
class TunnelConfig(config.Config):
    host: str
    port: int = config.value(converter=config.str_to_int)


@config.config
class SourceConfig(config.Config):
    host: str
    password: str
    port: int = config.value(converter=config.str_to_int)
    tunnel: TunnelConfig | None = None


cfg = SourceConfig.from_dict({"host": "db.example.com", "password": "hunter2", "port": "5432"})
```

- `@config` makes a dataclass with `from_dict` and `validate_dict`.
- `value(...)` sets an alias, a prefix or a converter on a field.
- A nested config reads its fields from a nested mapping or from prefixed flat keys, for example `tunnel_host`.
- `from_dict` raises `ConfigValueError` when a converter rejects a value, and `UndecryptedConfigError` when a value is still encrypted.
  Neither message contains the value.
- `repr` shows `'***'` for a field whose name contains a secret word, such as `password`, `token` or `key`.

Warehouse sources import this runtime through `products/warehouse_sources/backend/temporal/data_imports/sources/common/config.py`.

## Tests

```console
pytest packages/typed-config
```
