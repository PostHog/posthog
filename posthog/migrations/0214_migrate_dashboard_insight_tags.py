# Generated by Django 3.2.5 on 2022-01-28 21:40
from django.db import migrations
from django.db.models import Q

from posthog.models.tag import tagify


def forwards(apps, schema_editor):
    Tag = apps.get_model("posthog", "Tag")
    TaggedItem = apps.get_model("posthog", "TaggedItem")
    tags_to_create = []  # type: ignore
    tagged_items_to_create = []

    # Create new insight tags
    Insight = apps.get_model("posthog", "Insight")
    for instance in Insight.objects.exclude(deprecated_tags__isnull=True, deprecated_tags=[]):
        if instance.deprecated_tags:
            unique_tags = set([tagify(t) for t in instance.deprecated_tags])
            for tag in unique_tags:
                new_tag = Tag.objects.filter(name=tag, team_id=instance.team_id).first()
                if not new_tag:
                    new_tag = next(
                        filter(lambda t: t.name == tag and t.team_id == instance.team_id, tags_to_create), None
                    )
                    if not new_tag:
                        new_tag = Tag(name=tag, team_id=instance.team_id)
                        tags_to_create.append(new_tag)
                tagged_items_to_create.append(TaggedItem(insight_id=instance.id, tag_id=new_tag.id))

    # Create new dashboard tags
    Dashboard = apps.get_model("posthog", "Dashboard")
    for instance in Dashboard.objects.exclude(deprecated_tags__isnull=True, deprecated_tags=[]):
        if instance.deprecated_tags:
            unique_tags = set([tagify(t) for t in instance.deprecated_tags])
            for tag in unique_tags:
                new_tag = Tag.objects.filter(name=tag, team_id=instance.team_id).first()
                if not new_tag:
                    new_tag = next(
                        filter(lambda t: t.name == tag and t.team_id == instance.team_id, tags_to_create), None
                    )
                    if not new_tag:
                        new_tag = Tag(name=tag, team_id=instance.team_id)
                        tags_to_create.append(new_tag)
                tagged_items_to_create.append(TaggedItem(dashboard_id=instance.id, tag_id=new_tag.id))

    Tag.objects.bulk_create(tags_to_create)
    TaggedItem.objects.bulk_create(tagged_items_to_create)


def reverse(apps, schema_editor):
    EnterpriseTaggedItem = apps.get_model("posthog", "TaggedItem")
    EnterpriseTaggedItem.objects.filter(Q(dashboard_id__isnull=False) | Q(insight_id__isnull=False)).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0213_deprecated_old_tags"),
    ]

    operations = [migrations.RunPython(forwards, reverse)]
