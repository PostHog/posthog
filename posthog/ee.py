from django.conf import settings


# add all conditions to check here
def is_ee_enabled() -> bool:
    flag_enabled = settings.PRIMARY_DB == settings.CLICKHOUSE
    return flag_enabled
