from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PgLSN:
    """PostgreSQL Log Sequence Number (LSN).

    Internally stored as a 64-bit integer. Serialized as the standard
    Postgres format: "upper32/lower32" (e.g. "0/16B3748").
    """

    value: int

    def serialize(self) -> str:
        upper = (self.value >> 32) & 0xFFFFFFFF
        lower = self.value & 0xFFFFFFFF
        return f"{upper:X}/{lower:X}"

    @classmethod
    def deserialize(cls, value: str) -> PgLSN:
        upper_str, lower_str = value.split("/")
        upper = int(upper_str, 16)
        lower = int(lower_str, 16)
        return cls(value=(upper << 32) | lower)

    @classmethod
    def from_bytes(cls, data: bytes) -> PgLSN:
        """Parse an 8-byte big-endian LSN from binary pgoutput data."""
        return cls(value=int.from_bytes(data[:8], byteorder="big"))

    def __le__(self, other: PgLSN) -> bool:
        return self.value <= other.value

    def __lt__(self, other: PgLSN) -> bool:
        return self.value < other.value

    def __repr__(self) -> str:
        return f"PgLSN({self.serialize()})"
