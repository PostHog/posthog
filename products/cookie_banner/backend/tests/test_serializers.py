from unittest.mock import MagicMock

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cookie_banner.backend.presentation.serializers import CookieBannerConfigSerializer


def _serializer(appearance: dict, white_labelling_available: bool = False) -> CookieBannerConfigSerializer:
    organization = MagicMock()
    organization.is_feature_available.return_value = white_labelling_available
    return CookieBannerConfigSerializer(
        data={"enabled": True, "appearance": appearance},
        context={"get_organization": lambda: organization},
    )


class TestCookieBannerAppearanceValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("unknown_art_style", {"artStyle": "dancing-hog"}),
            ("unknown_position", {"position": "top-bar"}),
            ("non_hex_color", {"backgroundColor": "red"}),
            ("css_injection_in_color", {"buttonColor": "#fff; } body { display: none"}),
            ("title_too_long", {"title": "a" * 26}),
            ("description_too_long", {"description": "a" * 201}),
            ("accept_button_text_too_long", {"acceptButtonText": "a" * 12}),
            ("decline_button_text_too_long", {"declineButtonText": "a" * 12}),
            ("preferences_button_text_too_long", {"preferencesButtonText": "a" * 26}),
            ("invalid_language_code", {"translations": {"deutsch": {"title": "Hallo"}}}),
            ("translated_title_too_long", {"translations": {"de": {"title": "a" * 26}}}),
            ("translation_not_an_object", {"translations": {"de": "Hallo"}}),
            (
                "too_many_languages",
                {"translations": {f"a{chr(ord('a') + i)}": {"title": "x"} for i in range(21)}},
            ),
        ]
    )
    def test_rejects_invalid_appearance(self, _name: str, appearance: dict) -> None:
        serializer = _serializer(appearance)
        assert not serializer.is_valid()
        assert "appearance" in serializer.errors

    def test_accepts_valid_appearance(self) -> None:
        serializer = _serializer(
            {
                "title": "We use cookies",
                "description": "Details here",
                "acceptButtonText": "OK",
                "declineButtonText": "No",
                "artStyle": "hedgehog-builder",
                "position": "bottom-bar",
                "backgroundColor": "#ffffff",
                "textColor": "#000",
                "buttonColor": "#f54e00",
                "buttonTextColor": "#ffffffff",
            }
        )
        assert serializer.is_valid(), serializer.errors

    def test_unknown_appearance_keys_are_stripped(self) -> None:
        serializer = _serializer({"title": "Hi", "onload": "alert(1)"})
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["appearance"] == {"title": "Hi"}

    def test_translations_accepted_and_unknown_keys_stripped(self) -> None:
        serializer = _serializer(
            {
                "showPreferences": True,
                "cookielessFallback": True,
                "respectGpc": False,
                "translations": {
                    "de": {"title": "Wir verwenden Cookies", "backgroundColor": "#000000"},
                    "pt-BR": {"acceptButtonText": "Aceitar"},
                },
            }
        )
        assert serializer.is_valid(), serializer.errors
        translations = serializer.validated_data["appearance"]["translations"]
        # Only copy fields survive: a translation must not be able to override colors or art
        assert translations["de"] == {"title": "Wir verwenden Cookies"}
        assert translations["pt-BR"] == {"acceptButtonText": "Aceitar"}

    def test_white_label_requires_entitlement(self) -> None:
        serializer = _serializer({"whiteLabel": True}, white_labelling_available=False)
        assert not serializer.is_valid()
        assert "appearance" in serializer.errors

    @parameterized.expand(
        [
            ("with_entitlement", {"whiteLabel": True}, True),
            ("disabling_never_gated", {"whiteLabel": False}, False),
        ]
    )
    def test_white_label_allowed(self, _name: str, appearance: dict, white_labelling_available: bool) -> None:
        serializer = _serializer(appearance, white_labelling_available=white_labelling_available)
        assert serializer.is_valid(), serializer.errors
