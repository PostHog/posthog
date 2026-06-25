from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0008_alter_evaluation_status_reason"),
    ]

    operations = [
        migrations.AlterField(
            model_name="llmproviderkey",
            name="provider",
            field=models.CharField(
                choices=[
                    ("openai", "Openai"),
                    ("anthropic", "Anthropic"),
                    ("gemini", "Gemini"),
                    ("openrouter", "Openrouter"),
                    ("fireworks", "Fireworks"),
                    ("azure_openai", "Azure OpenAI"),
                    ("together_ai", "Together AI"),
                    ("deepseek", "DeepSeek"),
                ],
                max_length=50,
            ),
        ),
    ]
