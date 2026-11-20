from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0063_node_subscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="datamodelingjob",
            name="result_bytes_received",
            field=models.BigIntegerField(
                blank=True,
                help_text="Bytes of ClickHouse response body the worker read, including retries.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="datamodelingjob",
            name="delta_files_written",
            field=models.IntegerField(
                blank=True,
                help_text="Data files added to the Delta table, including compaction and retries.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="datamodelingjob",
            name="delta_bytes_written",
            field=models.BigIntegerField(
                blank=True,
                help_text="Bytes of data files added to the Delta table, including compaction and retries.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="datamodelingjob",
            name="delta_table_files",
            field=models.IntegerField(
                blank=True,
                help_text="Live data files in the Delta table after the run. Publishing copies each.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="datamodelingjob",
            name="delta_table_bytes",
            field=models.BigIntegerField(
                blank=True,
                help_text="Bytes of live data files in the Delta table after the run.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="datamodelingjob",
            name="activity_seconds",
            field=models.FloatField(
                blank=True,
                help_text="Seconds the materialize activity ran, including retries.",
                null=True,
            ),
        ),
    ]
