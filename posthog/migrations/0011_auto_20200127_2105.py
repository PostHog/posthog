# Generated by Django 2.2.7 on 2020-01-27 21:05

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0010_funnel_funnelstep"),
    ]

    operations = [
        migrations.RemoveField(model_name="element", name="team",),
        migrations.RemoveField(model_name="person", name="distinct_ids",),
        migrations.AddField(
            model_name="event",
            name="distinct_id",
            field=models.CharField(
                default="fake-id-that-shouldnt-exist", max_length=200
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="element",
            name="nth_child",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="element",
            name="nth_of_type",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="element",
            name="order",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="event",
            name="ip",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="funnelstep",
            name="funnel",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="steps",
                to="posthog.Funnel",
            ),
        ),
        migrations.CreateModel(
            name="PersonDistinctId",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("distinct_id", models.CharField(max_length=400)),
                (
                    "person",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="posthog.Person"
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="posthog.Team"
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="persondistinctid",
            constraint=models.UniqueConstraint(
                fields=("team", "distinct_id"), name="unique distinct_id for team"
            ),
        ),
    ]
