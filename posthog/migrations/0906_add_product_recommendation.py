# Generated manually for product recommendations feature

import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0905_alter_person_table"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductRecommendation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "recommended_product",
                    models.CharField(help_text="The product type recommended as the next best product", max_length=255),
                ),
                (
                    "product_sequence_state_before",
                    models.JSONField(
                        default=list,
                        help_text="Ordered list of products the organization had before this recommendation",
                    ),
                ),
                (
                    "num_products_before",
                    models.IntegerField(
                        default=0,
                        help_text="Number of products the organization had before this recommendation",
                    ),
                ),
                (
                    "calculated_at",
                    models.DateTimeField(
                        help_text="When this recommendation was calculated",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="product_recommendation",
                        to="posthog.organization",
                    ),
                ),
            ],
        ),
    ]
