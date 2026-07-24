"""DRF serializers for cookie_banner."""

import re
from typing import Any

from django.db import IntegrityError

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.constants import AvailableFeature

from products.cookie_banner.backend.constants import (
    ART_STYLES,
    HEX_COLOR_REGEX,
    LANGUAGE_CODE_REGEX,
    MAX_TEXT_LENGTHS,
    MAX_TRANSLATION_LANGUAGES,
    POSITIONS,
)
from products.cookie_banner.backend.models import CookieBannerConfig

_ALREADY_EXISTS_ERROR = "A cookie banner already exists for this project. Update the existing one instead."


def _color_field(help_text: str) -> serializers.RegexField:
    return serializers.RegexField(
        regex=HEX_COLOR_REGEX,
        required=False,
        help_text=help_text,
        error_messages={"invalid": "Must be a hex color, e.g. #f54e00"},
    )


class CookieBannerTranslationSerializer(serializers.Serializer):
    """Per-language overrides for the banner copy. Omitted keys fall back to the base
    (untranslated) copy for visitors matching this language."""

    title = serializers.CharField(
        required=False,
        max_length=MAX_TEXT_LENGTHS["title"],
        help_text="Translated banner headline.",
    )
    description = serializers.CharField(
        required=False,
        max_length=MAX_TEXT_LENGTHS["description"],
        help_text="Translated body copy.",
    )
    acceptButtonText = serializers.CharField(
        required=False,
        max_length=MAX_TEXT_LENGTHS["acceptButtonText"],
        help_text="Translated accept button label.",
    )
    declineButtonText = serializers.CharField(
        required=False,
        max_length=MAX_TEXT_LENGTHS["declineButtonText"],
        help_text="Translated decline button label.",
    )
    preferencesButtonText = serializers.CharField(
        required=False,
        max_length=MAX_TEXT_LENGTHS["preferencesButtonText"],
        help_text="Translated 'Manage preferences' label.",
    )


class CookieBannerAppearanceSerializer(serializers.Serializer):
    """Appearance overrides for the banner. Omitted keys fall back to the PostHog-styled defaults
    (see products/cookie_banner/backend/constants.py) when the banner is delivered."""

    title = serializers.CharField(
        required=False,
        max_length=MAX_TEXT_LENGTHS["title"],
        help_text="Banner headline. Plain text only. Defaults to 'We use cookies'.",
    )
    description = serializers.CharField(
        required=False,
        max_length=MAX_TEXT_LENGTHS["description"],
        help_text="Body copy explaining what cookies are used for. Plain text only.",
    )
    acceptButtonText = serializers.CharField(
        required=False,
        max_length=MAX_TEXT_LENGTHS["acceptButtonText"],
        help_text="Label for the button that opts the visitor in to tracking. Defaults to 'Accept'.",
    )
    declineButtonText = serializers.CharField(
        required=False,
        max_length=MAX_TEXT_LENGTHS["declineButtonText"],
        help_text="Label for the button that opts the visitor out of tracking. Defaults to 'Decline'.",
    )
    artStyle = serializers.ChoiceField(
        required=False,
        choices=ART_STYLES,
        help_text="Artwork shown on the banner: the PostHog logo, hedgehog art, or none. Defaults to 'posthog-logo'.",
    )
    position = serializers.ChoiceField(
        required=False,
        choices=POSITIONS,
        help_text="Where the banner appears on the page. Defaults to 'bottom-right'.",
    )
    backgroundColor = _color_field("Banner background color as a hex value. Defaults to '#eeefe9'.")
    textColor = _color_field("Banner text color as a hex value. Defaults to '#151515'.")
    buttonColor = _color_field("Accept button background color as a hex value. Defaults to '#f54e00'.")
    buttonTextColor = _color_field("Accept button text color as a hex value. Defaults to '#ffffff'.")
    whiteLabel = serializers.BooleanField(
        required=False,
        help_text="Hide the 'Powered by PostHog' notice. Requires the white labelling entitlement on your plan.",
    )
    preferencesButtonText = serializers.CharField(
        required=False,
        max_length=MAX_TEXT_LENGTHS["preferencesButtonText"],
        help_text="Label for the link that opens the consent preferences panel. Defaults to 'Manage preferences'.",
    )
    showPreferences = serializers.BooleanField(
        required=False,
        help_text="Show a 'Manage preferences' panel where visitors can consent to analytics and marketing cookies separately. Category choices are exposed to your site via the posthog:consent event. Defaults to false.",
    )
    cookielessFallback = serializers.BooleanField(
        required=False,
        help_text="When a visitor declines analytics cookies, keep anonymous cookieless analytics (in-memory persistence, nothing stored on the device) instead of stopping tracking entirely. Defaults to false.",
    )
    respectGpc = serializers.BooleanField(
        required=False,
        help_text="Visitors broadcasting the Global Privacy Control signal are treated as declined and never shown the banner. An explicit choice made on your site still takes precedence. Defaults to true.",
    )
    translations = serializers.DictField(
        child=CookieBannerTranslationSerializer(),
        required=False,
        help_text="Per-language copy overrides keyed by ISO 639 language code (e.g. 'de', 'pt-BR'). The banner picks the visitor's browser language, falling back to the base copy.",
    )

    def validate_translations(self, value: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        if len(value) > MAX_TRANSLATION_LANGUAGES:
            raise serializers.ValidationError(f"At most {MAX_TRANSLATION_LANGUAGES} languages are supported.")
        for language in value:
            if not re.match(LANGUAGE_CODE_REGEX, language):
                raise serializers.ValidationError(
                    f"'{language}' is not a valid language code. Use an ISO 639 code like 'de' or 'pt-BR'."
                )
        return value


class CookieBannerConfigSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, help_text="User who created the banner.")
    enabled = serializers.BooleanField(
        required=False,
        help_text="Whether the banner is served to your website. Defaults to false.",
    )
    appearance = CookieBannerAppearanceSerializer(
        required=False,
        help_text="Appearance and copy overrides. Omitted keys use the PostHog-styled defaults.",
    )

    class Meta:
        model = CookieBannerConfig
        fields = ["id", "enabled", "appearance", "created_at", "created_by", "updated_at"]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]
        extra_kwargs = {
            "id": {"help_text": "Unique id of the banner config."},
            "created_at": {"help_text": "When the banner config was created."},
            "updated_at": {"help_text": "When the banner config was last updated."},
        }

    def validate_appearance(self, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("whiteLabel") and not self.context["get_organization"]().is_feature_available(
            AvailableFeature.WHITE_LABELLING
        ):
            raise serializers.ValidationError(
                "You need to upgrade to a plan with white labelling to hide PostHog branding"
            )
        return value

    def create(self, validated_data: dict[str, Any]) -> CookieBannerConfig:
        team = self.context["get_team"]()
        if CookieBannerConfig.objects.for_team(team.id).exists():
            raise serializers.ValidationError(_ALREADY_EXISTS_ERROR)
        try:
            return CookieBannerConfig.objects.create(
                team=team,
                created_by=self.context["request"].user,
                **validated_data,
            )
        except IntegrityError:
            raise serializers.ValidationError(_ALREADY_EXISTS_ERROR)

    def update(self, instance: CookieBannerConfig, validated_data: dict[str, Any]) -> CookieBannerConfig:
        # Explicit update because ModelSerializer rejects writable nested fields by default
        if "enabled" in validated_data:
            instance.enabled = validated_data["enabled"]
        if "appearance" in validated_data:
            instance.appearance = validated_data["appearance"]
        instance.save()
        return instance
