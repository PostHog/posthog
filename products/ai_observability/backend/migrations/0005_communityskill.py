import django.utils.timezone
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0004_parserrecipe"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CommunitySkill",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("slug", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=64)),
                ("description", models.CharField(max_length=4096)),
                ("body", models.TextField()),
                ("license", models.CharField(blank=True, default="", max_length=255)),
                ("compatibility", models.CharField(blank=True, default="", max_length=500)),
                ("allowed_tools", models.JSONField(blank=True, default=list)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("tags", models.JSONField(blank=True, default=list)),
                (
                    "trust_tier",
                    models.CharField(
                        choices=[
                            ("official", "Official"),
                            ("verified", "Verified"),
                            ("community", "Community"),
                        ],
                        default="community",
                        max_length=20,
                    ),
                ),
                ("author_handle", models.CharField(blank=True, default="", max_length=255)),
                ("github_url", models.CharField(blank=True, default="", max_length=8201)),
                ("source_sha", models.CharField(blank=True, default="", max_length=64)),
                ("install_count", models.PositiveIntegerField(default=0)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted", models.BooleanField(default=False)),
            ],
            options={
                "db_table": "llm_analytics_communityskill",
            },
        ),
        migrations.CreateModel(
            name="CommunitySkillFile",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("path", models.CharField(max_length=500)),
                ("content", models.TextField()),
                ("content_type", models.CharField(default="text/plain", max_length=100)),
                (
                    "skill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="files",
                        to="ai_observability.communityskill",
                    ),
                ),
            ],
            options={
                "db_table": "llm_analytics_communityskillfile",
            },
        ),
        migrations.CreateModel(
            name="CommunitySkillVote",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "skill",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="votes",
                        to="ai_observability.communityskill",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "llm_analytics_communityskillvote",
            },
        ),
        migrations.AddConstraint(
            model_name="communityskillfile",
            constraint=models.UniqueConstraint(fields=("skill", "path"), name="unique_community_skill_file_path"),
        ),
        migrations.AddConstraint(
            model_name="communityskillvote",
            constraint=models.UniqueConstraint(fields=("skill", "user"), name="unique_community_skill_vote_per_user"),
        ),
    ]
