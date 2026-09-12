import json
import base64
from dataclasses import replace
from pathlib import Path

from unittest import TestCase
from unittest.mock import MagicMock

from posthog.ai_training_privacy_reader import (
    TrainingDataKey,
    TrainingDataKeyReader,
    TrainingKeyIdentity,
    TrainingKeyLocation,
)


class TestTrainingDataKeyReader(TestCase):
    def test_shared_node_envelope_and_owner_binding(self) -> None:
        path = (
            Path(__file__).parents[2]
            / "nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/privacy/encryption-vector.json"
        )
        vector = json.loads(path.read_text())
        identity = TrainingKeyIdentity(
            team_id=vector["context"]["teamId"],
            organization_id=vector["context"]["organizationId"],
            session_id=vector["context"]["sessionId"],
            consent_granted_at=vector["context"]["consentGrantedAt"],
        )
        key = TrainingDataKey(identity=identity, plaintext=base64.b64decode(vector["key"]))
        envelope = json.dumps(vector["envelope"]).encode()
        self.assertEqual(key.decrypt(envelope, "rrweb"), base64.b64decode(vector["data"]))
        for wrong_key in [
            replace(key, identity=replace(identity, team_id=8)),
            replace(key, identity=replace(identity, consent_granted_at=identity.consent_granted_at + 1)),
        ]:
            with self.assertRaises(ValueError):
                wrong_key.decrypt(envelope, "rrweb")
        with self.assertRaises(ValueError):
            key.decrypt(envelope, "score")
        with self.assertRaises(TimeoutError):
            replace(key, decrypt_until=0).decrypt(envelope, "rrweb")

    def test_cache_cannot_restore_a_deleted_key_or_withdrawn_consent(self) -> None:
        location = TrainingKeyLocation.session(7, "01994569-4380-7000-8000-000000000007")
        consent = TrainingKeyLocation(pk="organization:test", sk="consent")
        rows = {
            location: {
                **location.encoded(),
                "team_id": {"N": "7"},
                "organization_id": {"S": "test"},
                "granted_at": {"N": "1"},
                "wrapped_key": {"B": b"wrapped"},
            },
            consent: {**consent.encoded(), "allowed": {"BOOL": True}, "granted_at": {"N": "1"}},
        }
        dynamo = MagicMock()
        dynamo.batch_get_item.side_effect = lambda **kwargs: {
            "Responses": {
                "table": [
                    rows[loc]
                    for item in kwargs["RequestItems"]["table"]["Keys"]
                    if (loc := TrainingKeyLocation(pk=item["pk"]["S"], sk=item["sk"]["S"])) in rows
                ]
            }
        }
        kms = MagicMock()
        kms.decrypt.return_value = {"Plaintext": bytes([7]) * 32}
        reader = TrainingDataKeyReader(dynamo, kms, "table", "kms-key")
        self.assertIn(location, reader.read([location]))
        self.assertIn(location, reader.read([location]))
        self.assertEqual(kms.decrypt.call_count, 1)
        month = TrainingKeyLocation(pk="month:2025-09", sk="deleted")
        rows[month] = {**month.encoded(), "deleted": {"BOOL": True}}
        self.assertEqual(reader.read([location]), {})
        del rows[month]
        rows[consent]["allowed"] = {"BOOL": False}
        self.assertEqual(reader.read([location]), {})
        rows[consent]["allowed"] = {"BOOL": True}
        rows[location].pop("wrapped_key")
        rows[location]["deleted"] = {"BOOL": True}
        self.assertEqual(reader.read([location]), {})
        self.assertEqual(kms.decrypt.call_count, 1)
