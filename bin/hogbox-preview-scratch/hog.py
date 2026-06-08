"""Local hogland-dev client helper. Token read from the CLI config, never printed."""
import json
import os
import pathlib

import httpx
from hogland import Hogland

# Snapshot restores + long execs (hogli up) far exceed the SDK's default read
# timeout, so give it generous headroom.
TIMEOUT = httpx.Timeout(connect=15.0, read=2000.0, write=120.0, pool=120.0)

HOSTS = {
    "dev": "https://hogland-dev.hedgehog-kitefin.ts.net",
    "prod-us": "https://hogland.hedgehog-kitefin.ts.net",
}
HOST = HOSTS.get(os.environ.get("HOGENV", "dev"), HOSTS["dev"])


def client() -> Hogland:
    cfg = json.loads((pathlib.Path.home() / ".config/hogland/config.json").read_text())
    return Hogland(base_url=HOST, token=cfg["token"], timeout=TIMEOUT)
