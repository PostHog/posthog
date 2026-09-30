import re
from urllib.parse import urlsplit

from django.db import migrations

# A frozen copy of the alerts naming rule, so later edits to the product code cannot change what
# this migration did.
# The first branch takes the URL the builder appended, which runs to the end of the name. It is
# tried first because an apostrophe and a double quote are both legal in a URL path and query
# (RFC 3986 sub-delims), so the bounded branch would stop at one and leave the rest of the
# credential in the name. The bounded branch then covers a URL the alert's own name carried,
# which has text after it, and ends on a non-punctuation character so a following bracket or
# comma stays in the text.
_URL_IN_NAME_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://(?:\S*$|[^\s'\"]*[^\s'\".,;:!?)\]}>])")
_FILE_SYSTEM_TYPE = "hog_function/internal_destination"


def _host(match: re.Match[str]) -> str:
    # hostname, not the raw authority: it drops any user:password@ prefix.
    try:
        return urlsplit(match.group(0)).hostname or "destination"
    except ValueError:
        return "destination"


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
        new_name = _URL_IN_NAME_RE.sub(_host, old_name)
        if new_name == old_name:
            continue
        HogFunction.objects.filter(id=destination.id).update(name=new_name)

        old_segment = _escape_path_segment(old_name)
        new_segment = _escape_path_segment(new_name)
        tree_rows = {"team_id": destination.team_id, "type": _FILE_SYSTEM_TYPE, "ref": str(destination.id)}
        for entry in FileSystem.objects.filter(**tree_rows, path__endswith=old_segment).only("id", "path"):
            FileSystem.objects.filter(id=entry.id).update(path=entry.path[: -len(old_segment)] + new_segment)

        # A shortcut stores the name alone rather than the whole path, because the tree builds a
        # starred item's path from its last segment.
        FileSystemShortcut.objects.filter(**tree_rows, path=old_segment).update(path=new_segment)


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
