from django.conf import settings

_WRITER_ALIAS = "bets_db_writer"
_READER_ALIAS = "bets_db_reader"
WRITER_DB: str = _WRITER_ALIAS if _WRITER_ALIAS in settings.DATABASES else "default"
READER_DB: str = (
    _WRITER_ALIAS
    if getattr(settings, "TEST", False) and _WRITER_ALIAS in settings.DATABASES
    else (_READER_ALIAS if _READER_ALIAS in settings.DATABASES else "default")
)
