from django.db import migrations

# Kept as a literal rather than imported from the feature flags app: a migration has to keep
# applying the same way after the application constant moves or changes.
REDACTED_PAYLOAD_VALUE = '"********* (encrypted)"'

NON_TERMINAL_STATES = ("pending", "approved")

PAYLOAD_CLEARED_MESSAGE = (
    "This change request included a flag payload that was cleared for security. Submit the change again to apply it."
)


def _scrub(payload):
    """Replace every flag payload value with the sentinel, and report whether anything changed."""
    changed = False

    def walk(value):
        nonlocal changed
        if isinstance(value, dict):
            scrubbed = {}
            for key, item in value.items():
                if key == "filters" and isinstance(item, dict) and isinstance(item.get("payloads"), dict):
                    payloads = item["payloads"]
                    if any(entry != REDACTED_PAYLOAD_VALUE for entry in payloads.values()):
                        changed = True
                    scrubbed[key] = {**walk(item), "payloads": dict.fromkeys(payloads, REDACTED_PAYLOAD_VALUE)}
                else:
                    scrubbed[key] = walk(item)
            return scrubbed
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(payload), changed


def _stored_marker(intent):
    """Read `has_encrypted_payloads` out of a stored change, or None when it says nothing."""
    full_request_data = (intent or {}).get("full_request_data")
    if isinstance(full_request_data, dict) and "has_encrypted_payloads" in full_request_data:
        return bool(full_request_data["has_encrypted_payloads"])
    return None


def redact_stored_flag_payloads(apps, schema_editor):
    """Clear the flag payloads that change requests captured before the gate withheld them.

    A gated feature flag write reaches the approval gate before the serializer encrypts
    `filters.payloads`, so a change request stored the payload as it arrived. The gate now keeps
    the value out of the stored change, which leaves the rows written before that.

    Only a change whose flag keeps its payloads encrypted is scrubbed. The stored change decides
    when it records `has_encrypted_payloads`, and otherwise the flag does. That precision is what
    makes this safe to run more than once: a payload on a flag that does not encrypt its payloads
    is readable by design, so clearing it would destroy correct data and fail a valid approval
    with a message saying a secret was removed.

    A pending or approved row loses the payload it would have applied. Applying the rest would
    apply something other than what an approver agreed to, so those rows move to `failed` and the
    change has to be submitted again.

    This is a single pass over the rows that exist when it runs. A process still on the previous
    release can write one more plaintext row while the deployment rolls over, and nothing here
    revisits it. The read path keeps such a row's payload out of the API by asking the flag, so
    closing the remaining copy at rest means running this scrub again once the rollout has
    drained — which the paragraph above makes a no-op for everything it already settled.
    """
    ChangeRequest = apps.get_model("approvals", "ChangeRequest")

    resolved_flag_ids = {}

    def encrypted_flag_ids():
        """Every flag that keeps its payloads encrypted, read once and only when a row needs it.

        Soft-deleted flags are included: deleting a flag must not turn a withheld payload back
        into a readable one. Raw SQL against the table `FeatureFlag.Meta` pins keeps this
        migration off the feature flags app's migration state, and reading it lazily keeps a
        database with no change requests from touching that table at all.
        """
        if "ids" not in resolved_flag_ids:
            with schema_editor.connection.cursor() as cursor:
                cursor.execute("SELECT id FROM posthog_featureflag WHERE has_encrypted_payloads")
                resolved_flag_ids["ids"] = {row[0] for row in cursor.fetchall()}
        return resolved_flag_ids["ids"]

    def keeps_payloads_encrypted(change_request):
        marker = _stored_marker(change_request.intent)
        if marker is not None:
            return marker
        flag_id = (change_request.intent or {}).get("flag_id") or change_request.resource_id
        if not flag_id:
            # A create carries no flag to ask and no stored payload to protect.
            return False
        try:
            return int(flag_id) in encrypted_flag_ids()
        except (TypeError, ValueError):
            # An unreadable reference errs toward clearing, matching the read path.
            return True

    for change_request in ChangeRequest.objects.filter(resource_type="feature_flag").iterator(chunk_size=500):
        intent, intent_changed = _scrub(change_request.intent or {})
        intent_display, display_changed = _scrub(change_request.intent_display or {})
        if not intent_changed and not display_changed:
            continue
        if not keeps_payloads_encrypted(change_request):
            continue

        if change_request.state in NON_TERMINAL_STATES:
            # Compare-and-swap on the state read above: a row approved while this runs has already
            # applied its change, so it keeps the state it reached and only loses the payload.
            # Writing `failed` over it would tell the user to submit a change that is already live.
            moved = ChangeRequest.objects.filter(pk=change_request.pk, state__in=NON_TERMINAL_STATES).update(
                intent=intent,
                intent_display=intent_display,
                state="failed",
                apply_error=PAYLOAD_CLEARED_MESSAGE,
            )
            if moved:
                continue

        ChangeRequest.objects.filter(pk=change_request.pk).update(intent=intent, intent_display=intent_display)


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0003_alter_approvalpolicy_organization_and_more"),
    ]

    operations = [
        # Irreversible by design: the cleared values are not recoverable, so the reverse is a noop
        # rather than a restore.
        migrations.RunPython(redact_stored_flag_payloads, migrations.RunPython.noop, elidable=False),
    ]
