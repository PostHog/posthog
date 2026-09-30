import re
from urllib.parse import urlsplit

from django.db import migrations

# Frozen copies of the alerts naming rules, so later edits to the product code cannot change
# what this migration did.
_URL_IN_NAME_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s'\"]*[^\s'\".,;:!?)\]}>]")
# The builder appends the webhook URL last, so everything from the final scheme to the end of the
# name is that one URL. An apostrophe and a double quote are both legal in a URL path and query
# (RFC 3986 sub-delims), and the pattern above stops at either, which would leave the part of the
# credential that follows one in the name. Matching to the end of the name cannot.
_TRAILING_URL_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://\S*$")
_FILE_SYSTEM_TYPE = "hog_function/internal_destination"


def _host(url: str) -> str:
    try:
        return urlsplit(url).hostname or "destination"
    except ValueError:
        return "destination"


def _url_host(match: re.Match[str]) -> str:
    return _host(match.group(0))


def _redact_name(name: str) -> str:
    """Replace the trailing webhook URL, then any URL the alert's own name carried, with its host."""
    trailing = _TRAILING_URL_RE.search(name)
    if trailing:
        name = name[: trailing.start()] + _host(trailing.group(0))
    return _URL_IN_NAME_RE.sub(_url_host, name)


def _escape_path_segment(segment: str) -> str:
    return segment.replace("\\", "\\\\").replace("/", "\\/")


def redact_webhook_urls_in_destination_names(apps, schema_editor):
    """Alert-managed webhook destinations stored the full webhook URL in their name. The URL
    path and query carry the channel credential, so keep only the host. The project tree keeps
    its own copy of the name, in the FileSystem path and in the path of every shortcut a person
    starred it into, so rewrite those copies too."""
    HogFunction = apps.get_model("cdp", "HogFunction")
    FileSystem = apps.get_model("posthog", "FileSystem")
    FileSystemShortcut = apps.get_model("posthog", "FileSystemShortcut")

    destinations = (
        HogFunction.objects.filter(
            type="internal_destination",
            template_id="template-webhook",
            name__contains="://",
            filters__properties__contains=[{"key": "alert_id"}],
        )
        .only("id", "team_id", "name")
        .order_by("id")
    )

    for destination in destinations.iterator(chunk_size=500):
        old_name = destination.name
        new_name = _redact_name(old_name)
        if new_name == old_name:
            continue
        HogFunction.objects.filter(id=destination.id).update(name=new_name)

        old_segment = _escape_path_segment(old_name)
        new_segment = _escape_path_segment(new_name)
        for entry in FileSystem.objects.filter(
            team_id=destination.team_id, type=_FILE_SYSTEM_TYPE, ref=str(destination.id)
        ).only("id", "path"):
            if entry.path.endswith(old_segment):
                FileSystem.objects.filter(id=entry.id).update(path=entry.path[: -len(old_segment)] + new_segment)

        # A shortcut stores the name alone rather than the whole path, because the tree builds a
        # starred item's path from its last segment.
        FileSystemShortcut.objects.filter(
            team_id=destination.team_id,
            type=_FILE_SYSTEM_TYPE,
            ref=str(destination.id),
            path=old_segment,
        ).update(path=new_segment)


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0008_platformalert_firing_started_at_and_uuid7_pk"),
        ("cdp", "0005_repair_hogfunction_batch_export_id_index"),
    ]

    operations = [
        migrations.RunPython(
            redact_webhook_urls_in_destination_names,
            migrations.RunPython.noop,
            elidable=True,
        ),
    ]
