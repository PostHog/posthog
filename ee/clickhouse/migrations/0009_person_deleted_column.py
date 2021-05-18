from infi.clickhouse_orm import migrations  # type: ignore


class Migration(migrations.Migration):
    operations = [migrations.RunSQL("ALTER TABLE posthog.person ADD COLUMN IF NOT EXISTS deleted UInt8 DEFAULT 0")]
