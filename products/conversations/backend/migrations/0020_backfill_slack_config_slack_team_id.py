from django.db import migrations


def backfill_slack_team_id(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")
    SlackConfig = apps.get_model("conversations", "TeamConversationsSlackConfig")

    teams_with_slack = Team.objects.filter(
        conversations_settings__slack_team_id__isnull=False,
    ).values_list("id", "conversations_settings")

    for team_id, settings in teams_with_slack:
        slack_team_id = (settings or {}).get("slack_team_id")
        if not slack_team_id:
            continue
        SlackConfig.objects.filter(team_id=team_id).update(slack_team_id=slack_team_id)


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0019_slack_config_slack_team_id"),
        ("posthog", "1017_survey_form_content"),
    ]

    operations = [
        migrations.RunPython(backfill_slack_team_id, migrations.RunPython.noop),
    ]
