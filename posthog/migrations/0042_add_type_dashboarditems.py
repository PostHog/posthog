# Generated by Django 3.0.5 on 2020-04-09 10:55

from django.db import migrations
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS 

def update_filter_types(apps, schema_editor):
    DashboardItem = apps.get_model('posthog', 'DashboardItem')
    for item in DashboardItem.objects.filter(filters__actions__isnull=False):
        new_actions = []
        for action in item.filters['actions']:
            if isinstance(action['id'], int):
                action.update({'type': TREND_FILTER_TYPE_ACTIONS})
            else:
                action.update({'type': TREND_FILTER_TYPE_EVENTS})
            new_actions.append(action)
        item.filters['actions'] = new_actions
        item.save()

def reverse_filter_types(apps, schema_editor):
    DashboardItem = apps.get_model('posthog', 'DashboardItem')
    for item in DashboardItem.objects.filter(filters__actions__isnull=False):
        old_actions = []
        for action in item.filters['actions']:
            if isinstance(action['id'], int):
                action.pop('type')
            else:
                action.update({'type': TREND_FILTER_TYPE_EVENTS})
            old_actions.append(action)
        item.save()

class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0041_slack_webhooks'),
    ]

    operations = [
        migrations.RunPython(update_filter_types, reverse_filter_types)
    ]
