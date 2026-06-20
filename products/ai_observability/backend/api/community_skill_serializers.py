from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..models.community_skills import CommunitySkill, CommunitySkillFile, CommunitySkillTrustTier
from .skill_template_services import parse_template_variables

ALLOWED_LIST_ORDERINGS = frozenset(
    {
        "name",
        "-name",
        "created_at",
        "-created_at",
        "published_at",
        "-published_at",
        "install_count",
        "-install_count",
        "vote_count",
        "-vote_count",
    }
)


class CommunitySkillTemplateVariableSerializer(serializers.Serializer):
    """One declared variable of a templated skill — the schema a client renders a form from."""

    name = serializers.CharField(help_text="Variable identifier, substituted for `{{ name }}` in the skill body.")
    prompt = serializers.CharField(
        allow_blank=True,
        help_text="Human-readable question shown when collecting a value for this variable.",
    )
    is_required = serializers.BooleanField(
        help_text="Whether a value must be supplied at install time (otherwise it falls back to the default).",
    )
    default = serializers.CharField(
        allow_blank=True,
        help_text="Value used when none is supplied. Empty when the variable has no default.",
    )


class CommunitySkillFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommunitySkillFile
        fields = ["path", "content", "content_type"]


class CommunitySkillFileManifestSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommunitySkillFile
        fields = ["path", "content_type"]


class CommunitySkillSerializer(serializers.ModelSerializer):
    allowed_tools = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Tools the skill declares it may use. Surface these to the user before install.",
    )
    metadata = serializers.DictField(
        required=False,
        default=dict,
        help_text="Arbitrary key-value metadata carried from the skill's frontmatter.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Free-form tags used for filtering and discovery.",
    )
    trust_tier = serializers.ChoiceField(
        choices=CommunitySkillTrustTier.choices,
        help_text="Moderation tier: 'official' (PostHog-authored), 'verified' (reviewed), or 'community'.",
    )
    files = serializers.SerializerMethodField(
        help_text=(
            "Bundled files manifest (path + content_type only). Fetch full content via the skill detail endpoint."
        ),
    )
    template_variables = serializers.SerializerMethodField(
        help_text=(
            "Declared template variables, parsed from metadata. Non-empty marks this skill as a template: "
            "collect a value for each and pass them as `variables` when installing."
        ),
    )
    vote_count = serializers.SerializerMethodField(
        help_text="Total number of upvotes this skill has received.",
    )
    has_voted = serializers.SerializerMethodField(
        help_text="Whether the requesting user has upvoted this skill.",
    )

    class Meta:
        model = CommunitySkill
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "body",
            "license",
            "compatibility",
            "allowed_tools",
            "metadata",
            "tags",
            "trust_tier",
            "author_handle",
            "github_url",
            "files",
            "template_variables",
            "install_count",
            "vote_count",
            "has_voted",
            "published_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "slug": {"help_text": "Stable identifier matching the skill's directory in the community-skills repo."},
            "name": {"help_text": "Display name of the skill."},
            "description": {"help_text": "What the skill does and when to use it."},
            "body": {"help_text": "The SKILL.md instruction content (markdown)."},
            "license": {"help_text": "License name or reference."},
            "compatibility": {"help_text": "Environment requirements declared by the skill."},
            "author_handle": {"help_text": "GitHub handle (or name) of the contributor who published the skill."},
            "github_url": {"help_text": "Link to the skill's source directory on GitHub."},
            "install_count": {"help_text": "Number of times this skill has been installed into a team."},
            "published_at": {"help_text": "When the skill was first published to the community repo."},
        }

    @extend_schema_field(CommunitySkillFileManifestSerializer(many=True))
    def get_files(self, instance: CommunitySkill) -> list[dict[str, Any]]:
        return [dict(row) for row in instance.files.values("path", "content_type")]

    @extend_schema_field(CommunitySkillTemplateVariableSerializer(many=True))
    def get_template_variables(self, instance: CommunitySkill) -> list[dict[str, Any]]:
        return [
            {"name": v.name, "prompt": v.prompt, "is_required": v.required, "default": v.default}
            for v in parse_template_variables(instance.metadata)
        ]

    def get_vote_count(self, instance: CommunitySkill) -> int:
        # Provided by the viewset's annotated queryset; fall back to a count for unannotated instances.
        annotated = getattr(instance, "vote_count", None)
        return int(annotated) if annotated is not None else instance.votes.count()

    def get_has_voted(self, instance: CommunitySkill) -> bool:
        return bool(getattr(instance, "has_voted", False))


class CommunitySkillListSerializer(CommunitySkillSerializer):
    """List serializer that omits body and file manifest — progressive disclosure."""

    class Meta(CommunitySkillSerializer.Meta):
        fields = [f for f in CommunitySkillSerializer.Meta.fields if f not in ("body", "files")]
        read_only_fields = fields


class CommunitySkillListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Substring filter applied to skill names, descriptions, and tags.",
    )
    tag = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Return only skills carrying this tag.",
    )
    trust_tier = serializers.ChoiceField(
        choices=CommunitySkillTrustTier.choices,
        required=False,
        help_text="Filter to a single moderation tier.",
    )
    order_by = serializers.ChoiceField(
        choices=sorted(ALLOWED_LIST_ORDERINGS),
        required=False,
        default="-install_count",
        help_text="Sort key. Defaults to most-installed first.",
    )


class CommunitySkillInstallSerializer(serializers.Serializer):
    new_name = serializers.CharField(
        max_length=64,
        required=False,
        help_text="Name for the installed skill in your team. Defaults to the community skill's slug.",
    )
    variables = serializers.DictField(
        # trim_whitespace=False so a value's exact text (multiline snippets, leading/trailing
        # whitespace meant for the rendered output) survives into the installed skill.
        child=serializers.CharField(allow_blank=True, trim_whitespace=False),
        required=False,
        help_text=(
            "Values for a template skill's declared variables, as a {name: value} map. Required only when "
            "installing a template (see the skill's `template_variables`); ignored for non-template skills."
        ),
    )


class CommunitySkillVoteResponseSerializer(serializers.Serializer):
    vote_count = serializers.IntegerField(help_text="Total upvotes after applying the toggle.")
    has_voted = serializers.BooleanField(help_text="Whether the requesting user is now an upvoter.")
