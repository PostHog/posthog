from collections import namedtuple
import secrets


def namedtuplefetchall(cursor):
    """Return all rows from a cursor as a namedtuple"""
    desc = cursor.description
    nt_result = namedtuple("Result", [col[0] for col in desc])  # type: ignore
    return [nt_result(*row) for row in cursor.fetchall()]


def generate_random_token(length: int = 32) -> str:
    """Generate a securely random token"""
    return secrets.token_urlsafe(length)
