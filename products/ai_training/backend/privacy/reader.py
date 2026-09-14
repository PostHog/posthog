from __future__ import annotations

import re
import json
import time
import base64
import random
import hashlib
from collections import OrderedDict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import field
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol, TypedDict, cast

from nacl.secret import SecretBox

from posthog.dataclasses import frozen

KEY_READ_LEASE_SECONDS = 300

DynamoItem = dict[str, dict[str, str | bool | bytes]]


class BatchReadResponse(TypedDict, total=False):
    Responses: dict[str, list[DynamoItem]]
    UnprocessedKeys: dict[str, object]


class DynamoReader(Protocol):
    def batch_get_item(self, **kwargs: object) -> BatchReadResponse: ...


class KmsReader(Protocol):
    def decrypt(self, **kwargs: object) -> dict[str, bytes]: ...


@frozen
class TrainingKeyIdentity:
    team_id: int
    organization_id: str
    consent_granted_at: int
    session_id: str | None = None
    session_month: str | None = None

    def context(self, kind: str, ref: str | None = None) -> dict[str, str | int]:
        context: dict[str, str | int] = {
            "teamId": self.team_id,
            "organizationId": self.organization_id,
            "consentGrantedAt": self.consent_granted_at,
            "kind": kind,
        }
        if self.session_id is not None:
            context["sessionId"] = self.session_id
        if self.session_month is not None:
            context["sessionMonth"] = self.session_month
        if ref is not None:
            context["ref"] = ref
        return context

    def month_block_location(self) -> TrainingKeyLocation:
        month = self.session_month
        if self.session_id:
            timestamp_ms = int(self.session_id[:8] + self.session_id[9:13], 16)
            month = datetime.fromtimestamp(timestamp_ms / 1000, UTC).strftime("%Y-%m")
        if month is None or re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month) is None:
            raise ValueError("ML key requires a session month")
        return TrainingKeyLocation(pk=f"month:{month}", sk="deleted")

    def wrapping_context(self) -> dict[str, str]:
        context = {
            "purpose": "ai-research-session" if self.session_id else "ai-research-image",
            "team_id": str(self.team_id),
            "organization_id": self.organization_id,
            "consent_granted_at": str(self.consent_granted_at),
        }
        if self.session_id:
            context["session_id"] = self.session_id
        if self.session_month is not None:
            context["session_month"] = self.session_month
        return context


@frozen
class TrainingDataKey:
    identity: TrainingKeyIdentity
    plaintext: bytes = field(repr=False)
    decrypt_until: float = field(default_factory=lambda: time.monotonic() + KEY_READ_LEASE_SECONDS)

    def encrypt(self, kind: str, data: bytes, ref: str | None = None) -> bytes:
        context = self.identity.context(kind, ref)
        authenticated = json.dumps({"context": context, "data": base64.b64encode(data).decode()}).encode()
        encrypted = SecretBox(self.plaintext).encrypt(authenticated)
        return json.dumps(
            {
                "v": 2,
                "context": context,
                "nonce": base64.b64encode(encrypted.nonce).decode(),
                "ciphertext": base64.b64encode(encrypted.ciphertext).decode(),
            }
        ).encode()

    def decrypt(self, envelope_bytes: bytes, kind: str, ref: str | None = None) -> bytes:
        if time.monotonic() >= self.decrypt_until:
            raise TimeoutError("ML key read lease expired; read the key again")
        envelope = json.loads(envelope_bytes)
        context = self.identity.context(kind, ref)
        if envelope.get("v") != 2 or envelope.get("context") != context:
            raise ValueError("ML envelope context mismatch")
        decoded = json.loads(
            SecretBox(self.plaintext).decrypt(
                base64.b64decode(envelope["ciphertext"], validate=True),
                base64.b64decode(envelope["nonce"], validate=True),
            )
        )
        if decoded.get("context") != context:
            raise ValueError("ML authenticated context mismatch")
        return base64.b64decode(decoded["data"], validate=True)


@frozen
class TrainingKeyLocation:
    pk: str
    sk: str

    @classmethod
    def session(cls, team_id: int, session_id: str) -> TrainingKeyLocation:
        shard = int(hashlib.sha256(session_id.encode()).hexdigest()[:8], 16) % 32
        return cls(pk=f"team:{team_id}:shard:{shard}", sk=f"session:{session_id}")

    @classmethod
    def image(cls, team_id: int, consent_granted_at: int, session_month: str) -> TrainingKeyLocation:
        return cls(pk=f"team:{team_id}", sk=f"image:{consent_granted_at}:{session_month}")

    def encoded(self) -> DynamoItem:
        return {"pk": {"S": self.pk}, "sk": {"S": self.sk}}


class TrainingDataKeyReader:
    def __init__(
        self,
        dynamo: DynamoReader,
        kms: KmsReader,
        table_name: str,
        master_key_arn: str,
        cache_max: int = 10000,
        cache_seconds: int = 60,
        kms_requests_per_second: int = 20,
    ) -> None:
        if cache_max < 1 or cache_seconds < 1 or kms_requests_per_second < 1:
            raise ValueError("ML key cache and request limits must be positive")
        self.kms_requests_per_second = kms_requests_per_second
        self.next_request_at = 0.0
        self.lock = Lock()
        self.dynamo = dynamo
        self.kms = kms
        self.table_name = table_name
        self.master_key_arn = master_key_arn
        self.cache_max = cache_max
        self.cache_seconds = cache_seconds
        self.cache: OrderedDict[bytes, tuple[float, bytes]] = OrderedDict()

    def bulk_read(self, locations: Sequence[TrainingKeyLocation]) -> dict[TrainingKeyLocation, DynamoItem]:
        unique = list(dict.fromkeys(locations))
        result: dict[TrainingKeyLocation, DynamoItem] = {}
        for start in range(0, len(unique), 100):
            pending: dict[str, object] = {
                self.table_name: {
                    "Keys": [location.encoded() for location in unique[start : start + 100]],
                    "ConsistentRead": True,
                }
            }
            for attempt in range(5):
                response = self.dynamo.batch_get_item(RequestItems=pending)
                for row in response.get("Responses", {}).get(self.table_name, []):
                    result[TrainingKeyLocation(pk=str(row["pk"]["S"]), sk=str(row["sk"]["S"]))] = row
                pending = response.get("UnprocessedKeys", {})
                if not pending:
                    break
                time.sleep(random.uniform(0, min(1, 0.05 * 2**attempt)))
            if pending:
                raise TimeoutError("ML key batch read did not complete")
        return result

    def read(self, locations: Sequence[TrainingKeyLocation]) -> dict[TrainingKeyLocation, TrainingDataKey]:
        decrypt_until = time.monotonic() + KEY_READ_LEASE_SECONDS
        stored = self.bulk_read(locations)
        identities: dict[TrainingKeyLocation, TrainingKeyIdentity] = {}
        for location, row in stored.items():
            if row.get("deleted", {}).get("BOOL") is True or not row.get("wrapped_key", {}).get("B"):
                continue
            identities[location] = TrainingKeyIdentity(
                team_id=int(str(row["team_id"]["N"])),
                organization_id=str(row["organization_id"]["S"]),
                consent_granted_at=int(str(row["granted_at"]["N"])),
                session_id=location.sk.removeprefix("session:") if location.sk.startswith("session:") else None,
                session_month=str(row["session_month"]["S"]) if location.sk.startswith("image:") else None,
            )
        state = self.bulk_read(
            [
                location
                for identity in identities.values()
                for location in (
                    identity.month_block_location(),
                    TrainingKeyLocation(pk=f"organization:{identity.organization_id}", sk="consent"),
                    TrainingKeyLocation(pk=f"team:{identity.team_id}", sk="deleted"),
                )
            ]
        )
        eligible: dict[TrainingKeyLocation, TrainingKeyIdentity] = {}
        for location, identity in identities.items():
            consent = state.get(TrainingKeyLocation(pk=f"organization:{identity.organization_id}", sk="consent"), {})
            if (
                identity.month_block_location() in state
                or TrainingKeyLocation(pk=f"team:{identity.team_id}", sk="deleted") in state
                or consent.get("allowed", {}).get("BOOL") is not True
                or int(str(consent.get("granted_at", {}).get("N", "-1"))) != identity.consent_granted_at
            ):
                continue
            eligible[location] = identity
        with ThreadPoolExecutor(max_workers=8) as executor:
            plaintexts = executor.map(
                lambda location: self.decrypt_key(
                    eligible[location], cast(bytes, stored[location]["wrapped_key"]["B"])
                ),
                eligible,
            )
            return {
                location: TrainingDataKey(identity=eligible[location], plaintext=plaintext, decrypt_until=decrypt_until)
                for location, plaintext in zip(eligible, plaintexts, strict=True)
            }

    def decrypt_key(self, identity: TrainingKeyIdentity, wrapped: bytes) -> bytes:
        cache_id = hashlib.sha256(wrapped + json.dumps(identity.wrapping_context(), sort_keys=True).encode()).digest()
        with self.lock:
            cached = self.cache.get(cache_id)
            if cached and cached[0] > time.monotonic():
                self.cache.move_to_end(cache_id)
                return cached[1]
            scheduled_at = max(time.monotonic(), self.next_request_at)
            self.next_request_at = scheduled_at + 1 / self.kms_requests_per_second
        wait = scheduled_at - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        plaintext = self.kms.decrypt(
            KeyId=self.master_key_arn, CiphertextBlob=wrapped, EncryptionContext=identity.wrapping_context()
        )["Plaintext"]
        if len(plaintext) != SecretBox.KEY_SIZE:
            raise ValueError("Invalid ML data key")
        with self.lock:
            self.cache[cache_id] = (time.monotonic() + self.cache_seconds, plaintext)
            while len(self.cache) > self.cache_max:
                self.cache.popitem(last=False)
        return plaintext
