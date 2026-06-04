from uuid import uuid4

from unittest import mock

from django.test import TestCase

from django_display_ids import DisplayIDLookupError, ObjectNotFoundError, encode_display_id
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound

from posthog.api.display_id import serializes_display_id_as_pk
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.exported_recording import ExportedRecording

# ExportedRecording is an arbitrary UUID-keyed model used purely as a vehicle for serializing
# in memory — a prefix is mocked onto it per test, so no model in the repo needs a real prefix.


class _RecordingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExportedRecording
        fields = ["id"]


class _DeclaredIdRecordingSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ExportedRecording
        fields = ["id"]


class TestDisplayIdSerialization(TestCase):
    def test_no_prefix_leaves_id_as_uuid(self):
        recording_id = uuid4()
        serializer = _RecordingSerializer(instance=ExportedRecording(id=recording_id))

        self.assertIsInstance(serializer.fields["id"], serializers.UUIDField)
        self.assertEqual(serializer.data["id"], str(recording_id))
        self.assertNotIn("display_id", serializer.data)

    def test_id_is_display_id_by_default(self):
        recording_id = uuid4()
        with mock.patch.object(ExportedRecording, "display_id_prefix", "tst"):
            serializer = _RecordingSerializer(instance=ExportedRecording(id=recording_id))
            data = serializer.data

        self.assertEqual(data["id"], encode_display_id("tst", recording_id))
        self.assertTrue(data["id"].startswith("tst_"))
        self.assertNotIn("display_id", data)

    def test_display_id_as_pk_false_keeps_uuid_and_adds_display_id_field(self):
        recording_id = uuid4()
        with (
            mock.patch.object(ExportedRecording, "display_id_prefix", "tst"),
            mock.patch.object(ExportedRecording, "display_id_as_pk", False, create=True),
        ):
            data = _RecordingSerializer(instance=ExportedRecording(id=recording_id)).data

        self.assertEqual(data["id"], str(recording_id))
        self.assertEqual(data["display_id"], encode_display_id("tst", recording_id))

    def test_explicitly_declared_id_field_opts_out_of_the_swap(self):
        recording_id = uuid4()
        with mock.patch.object(ExportedRecording, "display_id_prefix", "tst"):
            serializer = _DeclaredIdRecordingSerializer(instance=ExportedRecording(id=recording_id))

            self.assertIsInstance(serializer.fields["id"], serializers.UUIDField)
            self.assertEqual(serializer.data["id"], str(recording_id))

    def test_serializes_display_id_as_pk_defaults_true(self):
        self.assertTrue(serializes_display_id_as_pk(ExportedRecording))
        with mock.patch.object(ExportedRecording, "display_id_as_pk", False, create=True):
            self.assertFalse(serializes_display_id_as_pk(ExportedRecording))


class _PrefixedModel:
    display_id_prefix = "tst"


class _UnprefixedModel:
    display_id_prefix = None


class _ResolverViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"


class TestDisplayIdObjectResolution(TestCase):
    """Unit-tests the get_object glue in TeamAndOrgViewSetMixin: which branch fires and how
    the resolver's exceptions map to lookup outcomes. resolve_object itself (encode/decode and
    the DB query) is the library's responsibility and tested upstream."""

    def _viewset(self, value: str | None) -> _ResolverViewSet:
        viewset = _ResolverViewSet()
        viewset.kwargs = {} if value is None else {"pk": value}
        return viewset

    def test_returns_none_for_model_without_prefix(self):
        queryset = mock.Mock(model=_UnprefixedModel)
        with mock.patch("posthog.api.routing.resolve_object") as resolve_object:
            result = self._viewset("anything")._get_object_by_display_id(queryset)

        self.assertIsNone(result)
        resolve_object.assert_not_called()

    def test_returns_none_when_no_lookup_value(self):
        queryset = mock.Mock(model=_PrefixedModel)
        with mock.patch("posthog.api.routing.resolve_object") as resolve_object:
            result = self._viewset(None)._get_object_by_display_id(queryset)

        self.assertIsNone(result)
        resolve_object.assert_not_called()

    def test_returns_resolved_object(self):
        queryset = mock.Mock(model=_PrefixedModel)
        sentinel = object()
        with mock.patch("posthog.api.routing.resolve_object", return_value=sentinel) as resolve_object:
            result = self._viewset("tst_abc")._get_object_by_display_id(queryset)

        self.assertIs(result, sentinel)
        resolve_object.assert_called_once_with(_PrefixedModel, "tst_abc", queryset=queryset)

    def test_falls_through_when_identifier_is_not_a_display_id(self):
        # A non-display-ID identifier (e.g. a human-friendly slug a viewset resolves itself) must
        # return None so the normal safely_get_object / default lookup still runs.
        queryset = mock.Mock(model=_PrefixedModel)
        with mock.patch("posthog.api.routing.resolve_object", side_effect=DisplayIDLookupError("nope")):
            result = self._viewset("ticket-123")._get_object_by_display_id(queryset)

        self.assertIsNone(result)

    def test_raises_not_found_for_unknown_object(self):
        queryset = mock.Mock(model=_PrefixedModel)
        with mock.patch("posthog.api.routing.resolve_object", side_effect=ObjectNotFoundError("gone")):
            with self.assertRaises(NotFound):
                self._viewset("tst_abc")._get_object_by_display_id(queryset)
