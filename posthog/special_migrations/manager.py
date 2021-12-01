# for now we're just using this so the django orm detects the model and creates migrations correctly
def init_special_migrations():
    from posthog.models.special_migration import SpecialMigration
