"""The string form of a reference to an integration row, for code that stores the reference outside the SDK."""

from __future__ import annotations

from uuid import UUID

from posthog.dataclasses import frozen


@frozen
class IntegrationReference:
    """A pointer to one integration row, stored as a string.

    Rows of the `Integration` model have int ids. Rows in the credentials service get a UUID id, and
    keep the old int id as `legacy_id`. So a stored reference is a decimal string ("123") for a legacy
    id, or a canonical UUID. Parse and format a stored reference only with this class.

    The SDK accessors take int ids. A UUID reference cannot resolve yet, so callers treat it as
    "not found".
    """

    legacy_id: int | None = None
    uuid: UUID | None = None

    def __post_init__(self) -> None:
        if (self.legacy_id is None) == (self.uuid is None):
            raise ValueError("An integration reference needs exactly one of legacy_id and uuid")
        # bool is an int subclass, so `True` would format as "True" and never parse back.
        if self.legacy_id is not None and (type(self.legacy_id) is not int or self.legacy_id < 0):
            raise ValueError("A legacy integration id must be a non-negative int")
        if self.uuid is not None and not isinstance(self.uuid, UUID):
            raise ValueError("The uuid of an integration reference must be a UUID")

    @classmethod
    def from_legacy_id(cls, legacy_id: int) -> IntegrationReference:
        return cls(legacy_id=legacy_id)

    @classmethod
    def parse(cls, value: str) -> IntegrationReference:
        """Read a stored reference. Raises ValueError for any string that `str()` does not give.

        Only the canonical forms parse: ASCII digits with no sign and no leading zero, or a lowercase
        hyphenated UUID. So each row has exactly one stored form, and an equality query finds it.
        """
        if not isinstance(value, str):
            raise ValueError("An integration reference must be a string")
        if value.isascii() and value.isdigit():
            if len(value) > 1 and value.startswith("0"):
                raise ValueError("An integration reference must not have a leading zero")
            return cls(legacy_id=int(value))
        try:
            uuid = UUID(value)
        except ValueError:
            raise ValueError("An integration reference must be a decimal id or a UUID") from None
        if str(uuid) != value:
            raise ValueError("An integration reference UUID must be in lowercase hyphenated form")
        return cls(uuid=uuid)

    def __str__(self) -> str:
        return str(self.legacy_id) if self.legacy_id is not None else str(self.uuid)
