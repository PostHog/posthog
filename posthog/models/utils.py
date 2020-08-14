from collections import namedtuple
from typing import List


def namedtuplefetchall(cursor) -> List[namedtuple]:
    "Return all rows from a cursor as a namedtuple"
    desc = cursor.description
    nt_result = namedtuple("Result", [col[0] for col in desc])  # type: ignore
    return [nt_result(*row) for row in cursor.fetchall()]
