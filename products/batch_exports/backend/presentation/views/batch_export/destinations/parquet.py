"""Compatibility for exports using legacy Parquet file extensions."""

import typing

from products.batch_exports.backend.models.batch_export import OBJECT_STORAGE_DESTINATIONS
from products.batch_exports.backend.service import coerce_config_to_declared_types

LEGACY_PARQUET_EXTENSION_HELP_TEXT = (
    "Whether Parquet files keep the compression codec in their extension, for example "
    "'.parquet.zst' rather than '.parquet'. Parquet records its codec inside the file, so new "
    "exports leave it out. An export that already wrote Parquet files before this setting existed "
    "keeps it, so that pipelines matching on the old names do not break. Has no effect on JSON "
    "Lines, which always carries the codec in its extension."
)


def _writes_compressed_parquet(config: dict[str, typing.Any]) -> bool:
    """Whether a config produces Parquet file names that carry a compression codec."""
    return config.get("file_format") == "Parquet" and config.get("compression") is not None


def _uses_legacy_parquet_extension(destination_type: str, stored_config: dict[str, typing.Any]) -> bool:
    """Whether an export's stored config already writes the codec into its Parquet file names.

    Reads through `coerce_config_to_declared_types`, because `EncryptedJSONField` stringifies
    scalars on write and the string "False" is truthy.
    """
    coerced = coerce_config_to_declared_types(destination_type, stored_config)
    stored = coerced.get("legacy_parquet_extension")
    if stored is None:
        # export was created before the `legacy_parquet_extension` field was added
        # so will use the legacy extension if it writes compressed Parquet files
        return _writes_compressed_parquet(coerced)
    return bool(stored)


def _set_default_parquet_extension(destination_type: str, config: dict[str, typing.Any]) -> None:
    """Opt a newly created destination into the standard `.parquet` extension.

    The workflow input dataclasses default this to `True`, so that an export whose Temporal
    schedule predates the field keeps the same file extension as before in order to maintain
    compatibility.
    """
    if destination_type in OBJECT_STORAGE_DESTINATIONS:
        config.setdefault("legacy_parquet_extension", False)


def _pin_existing_parquet_extension(destination_type: str, stored_config: dict[str, typing.Any]) -> None:
    """Record what an export's file names already look like, before a patch can change its format.

    An export that predates this setting has no value for it, and a missing value reads as the
    legacy naming. That is correct only for an export that already writes names carrying a codec,
    which means Parquet with a compression codec set. An export on JSON Lines, or on Parquet with
    no compression, has no such names to keep, so moving it to compressed Parquet has to produce
    `.parquet` rather than `.parquet.zst`.

    Takes the config as stored, before the incoming patch merges into it, so the value reflects
    what the export has been running rather than what it is moving to. An explicit value in the
    patch still wins, because the merge applies afterwards.
    """
    if destination_type not in OBJECT_STORAGE_DESTINATIONS:
        return

    stored_config.setdefault("legacy_parquet_extension", _writes_compressed_parquet(stored_config))
