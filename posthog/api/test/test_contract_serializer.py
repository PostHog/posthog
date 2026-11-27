from typing import Any, Generic, TypeVar

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django.urls import path

from drf_spectacular.generators import SchemaGenerator
from parameterized import parameterized
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.contract_serializer import ContractResponseSerializer
from posthog.api.documentation import extend_schema
from posthog.dataclasses import described, frozen
from posthog.enums import LabeledStrEnum


class SwatchShade(LabeledStrEnum):
    LIGHT = "light"
    DARK_GREY = "dark_grey"


@frozen
class _Swatch:
    name: str = described("The swatch name.")
    shade: SwatchShade = described("How dark the swatch is.")


@frozen
class _Palette:
    title: str = described("The palette title.")
    tags: list[dict[str, Any]] = described("Free-form tags.")
    swatches: list[_Swatch] = described("Every swatch in the palette.")
    note: str | None = described("A note about the palette.", default=None)


_Payload = TypeVar("_Payload", bound=_Swatch | _Palette)


@frozen
class _Wrapped(Generic[_Payload]):
    status: str = described("Whether the payload was read.")
    payload: _Payload | None = None


@frozen
class _Orphan:
    value: int = described("A value.")


@frozen
class _Holder:
    orphan: _Orphan = described("A contract that no serializer renders.")


@frozen
class _Conflicted:
    caption: str = described("From the contract.")


class ColorSwatchSerializer(ContractResponseSerializer):
    class Meta:
        dataclass = _Swatch


class ColorPaletteSerializer(ContractResponseSerializer):
    tags = serializers.JSONField()

    class Meta:
        dataclass = _Palette


class WrappedSwatchSerializer(ContractResponseSerializer):
    class Meta:
        dataclass = _Wrapped[_Swatch]


class HolderSerializer(ContractResponseSerializer):
    class Meta:
        dataclass = _Holder


class ConflictedSerializer(ContractResponseSerializer):
    caption = serializers.CharField(help_text="From the serializer.")

    class Meta:
        dataclass = _Conflicted


def _list_view(serializer_class: type[serializers.Serializer]) -> type[viewsets.ViewSet]:
    class ListView(viewsets.ViewSet):
        scope_object = "project"

        @extend_schema(responses={200: serializer_class})
        def list(self, request: Request) -> Response:
            return Response()

    return ListView


def _schema_components() -> dict[str, Any]:
    patterns = [
        path(
            f"api/projects/<str:parent_lookup_team_id>/{route}/", _list_view(serializer_class).as_view({"get": "list"})
        )
        for route, serializer_class in [("palette", ColorPaletteSerializer), ("wrapped", WrappedSwatchSerializer)]
    ]
    return SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)["components"]["schemas"]


class TestContractResponseSerializer(SimpleTestCase):
    components: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.components = _schema_components()

    def test_fields_follow_the_contract_order(self) -> None:
        palette = _Palette(title="Autumn", tags=[], swatches=[], note=None)

        assert list(ColorPaletteSerializer(palette).data) == ["title", "tags", "swatches", "note"]

    def test_a_field_with_a_dataclass_default_stays_required(self) -> None:
        assert self.components["ColorPalette"]["required"] == ["note", "swatches", "tags", "title"]

    @parameterized.expand(
        [("derived_field", "title", "The palette title."), ("declared_field", "tags", "Free-form tags.")]
    )
    def test_help_text_comes_from_the_contract(self, _name: str, field_name: str, help_text: str) -> None:
        assert self.components["ColorPalette"]["properties"][field_name]["description"] == help_text

    def test_a_nested_contract_renders_with_its_named_serializer(self) -> None:
        swatches = self.components["ColorPalette"]["properties"]["swatches"]

        assert swatches["items"] == {"$ref": "#/components/schemas/ColorSwatch"}

    def test_a_generic_contract_renders_its_type_argument(self) -> None:
        payload = self.components["WrappedSwatch"]["properties"]["payload"]

        assert payload["oneOf"] == [{"$ref": "#/components/schemas/ColorSwatch"}, {"type": "null"}]

    def test_a_labeled_enum_keeps_its_class_name(self) -> None:
        assert self.components["SwatchShadeEnum"]["enum"] == ["light", "dark_grey"]

    def test_components_are_named_after_the_serializer_class(self) -> None:
        assert {"ColorPalette", "ColorSwatch", "WrappedSwatch"} <= set(self.components)
        assert not {"_Palette", "_Swatch", "_Wrapped"} & set(self.components)

    @parameterized.expand(
        [
            ("nested_contract_without_a_serializer", HolderSerializer),
            ("declared_field_with_its_own_help_text", ConflictedSerializer),
        ]
    )
    def test_a_misconfigured_serializer_refuses_to_build_its_fields(
        self, _name: str, serializer_class: type[ContractResponseSerializer]
    ) -> None:
        with self.assertRaises(ImproperlyConfigured):
            _ = serializer_class().fields

    def test_a_second_serializer_for_the_same_contract_is_refused(self) -> None:
        with self.assertRaises(ImproperlyConfigured):

            class OtherSwatchSerializer(ContractResponseSerializer):
                class Meta:
                    dataclass = _Swatch
