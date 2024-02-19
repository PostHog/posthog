# Generated by Django 4.1.13 on 2024-02-15 16:50

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0388_add_schema_to_batch_exports"),
    ]

    operations = [
        migrations.RenameModel(old_name="DataWarehouseViewLink", new_name="DataWarehouseJoin"),
        migrations.AddField(
            model_name="DataWarehouseJoin",
            name="joining_table_name",
            field=models.CharField(max_length=400),
        ),
        migrations.RemoveField(
            model_name="DataWarehouseJoin",
            name="saved_query",
        ),
        migrations.RenameField(
            model_name="datawarehousejoin",
            old_name="from_join_key",
            new_name="source_table_key",
        ),
        migrations.RenameField(
            model_name="datawarehousejoin",
            old_name="to_join_key",
            new_name="joining_table_key",
        ),
        migrations.AddField(
            model_name="datawarehousejoin",
            name="source_table_name",
            field=models.CharField(max_length=400),
        ),
        migrations.RemoveField(
            model_name="datawarehousejoin",
            name="table",
        ),
        migrations.AddField(
            model_name="datawarehousejoin",
            name="field_name",
            field=models.CharField(max_length=400),
        ),
    ]
