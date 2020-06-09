# Generated by Django 3.0.5 on 2020-06-08 23:20

from django.db import migrations, connection
import os

def materialize_session(apps, schema_editor):
    Team = apps.get_model('posthog', 'Team')
    teams = Team.objects.all()
    for team in teams:
        file_path = os.path.join(os.path.dirname(__file__), 'sql/materialize_sessions.sql')
        materialize_sessions_sql = open(file_path).read()
        with connection.cursor() as cursor:
            cursor.execute(materialize_sessions_sql, [team.pk for _ in range(5)])

def reverse_materialize_session(apps, schema_editor):
    Team = apps.get_model('posthog', 'Team')
    teams = Team.objects.all()
    for team in teams:
        with connection.cursor() as cursor:
            cursor.execute('DROP MATERIALIZED VIEW IF EXISTS sessions_team_{}'.format(team.pk))

class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0057_action_updated_at'),
    ]

    operations = [
        migrations.RunPython(materialize_session, reverse_materialize_session)
    ]
