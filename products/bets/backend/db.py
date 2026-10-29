from django.conf import settings

_WRITER_ALIAS = "bets_db_writer"
WRITER_DB: str = _WRITER_ALIAS if _WRITER_ALIAS in settings.DATABASES else "default"
