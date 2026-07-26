import pytest

from parameterized import parameterized

from products.batch_exports.backend.temporal.pipeline.types import BatchExportError, BatchExportResult
from products.batch_exports.backend.temporal.utils import handle_non_retryable_errors


class ConfiguredError(Exception):
    pass


class ConfiguredSubclassError(ConfiguredError):
    pass


SameNamedConfiguredError = type("ConfiguredError", (Exception,), {})


async def test_handle_non_retryable_errors_returns_errors_matching_configured_class() -> None:
    @handle_non_retryable_errors((ConfiguredError,))
    async def raise_error() -> BatchExportResult:
        raise ConfiguredError("user error")

    result = await raise_error()

    assert result.error == BatchExportError(type="ConfiguredError", message="user error")


@parameterized.expand(
    [
        ("configured_subclass", ConfiguredSubclassError),
        ("unrelated_same_named_class", SameNamedConfiguredError),
    ]
)
async def test_handle_non_retryable_errors_reraises_non_matching_error(
    _name: str,
    error_type: type[Exception],
) -> None:
    @handle_non_retryable_errors((ConfiguredError,))
    async def raise_error() -> BatchExportResult:
        raise error_type("internal error")

    with pytest.raises(error_type, match="internal error"):
        await raise_error()
