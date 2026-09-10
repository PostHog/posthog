from dataclasses import asdict, dataclass
from hashlib import md5
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.models import Team


@dataclass
class WebJsUrl:
    id: int
    url: str
    type: str


def get_decide_site_functions(team: "Team", using_database: str = "default") -> list[dict]:
    from products.cdp.backend.models.hog_functions.hog_function import HogFunction

    sources = (
        HogFunction.objects.db_manager(using_database)
        .filter(
            team=team,
            enabled=True,
            type__in=("site_destination", "site_app"),
            transpiled__isnull=False,
        )
        .values_list(
            "id",
            "updated_at",
            "type",
        )
        .all()
    )

    def site_function_url(source: tuple) -> str:
        # this just hashes a timestamp
        # nosemgrep: python.lang.security.insecure-hash-algorithms-md5.insecure-hash-algorithm-md5
        hash = md5(str(source[1]).encode()).hexdigest()
        return f"/site_function/{source[0]}/{hash}/"

    return [
        asdict(WebJsUrl(source[0], site_function_url(source), source[2] or "site_destination")) for source in sources
    ]
