# Generated by Django 3.2.12 on 2022-03-24 06:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0223_organizationdomain"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationdomain", name="saml_acs_url", field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name="organizationdomain", name="saml_entity_id", field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name="organizationdomain", name="saml_x509_cert", field=models.TextField(blank=True),
        ),
    ]
