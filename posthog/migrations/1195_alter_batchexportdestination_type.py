from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1194_project_updated_at")]

    operations = [
        migrations.AlterField(
            model_name="batchexportdestination",
            name="type",
            field=models.CharField(
                choices=[
                    ("S3", "S3"),
                    ("AwsS3", "Aws S3"),
                    ("S3Compatible", "S3 Compatible"),
                    ("Snowflake", "Snowflake"),
                    ("Postgres", "Postgres"),
                    ("Redshift", "Redshift"),
                    ("BigQuery", "Bigquery"),
                    ("Databricks", "Databricks"),
                    ("AzureBlob", "Azure Blob"),
                    ("Workflows", "Workflows"),
                    ("HTTP", "Http"),
                    ("NoOp", "Noop"),
                    ("FileDownload", "File Download"),
                ],
                help_text="A choice of supported BatchExportDestination types.",
                max_length=64,
            ),
        ),
    ]
