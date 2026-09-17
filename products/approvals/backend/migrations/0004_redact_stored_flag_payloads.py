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


def redact_stored_flag_payloads(apps, schema_editor):
    """Clear flag payloads that change requests captured before the gate withheld them.

    A gated feature flag write reaches the approval gate before the serializer encrypts
    `filters.payloads`, so a change request stored the payload as it arrived. The gate now
    keeps the value out of the stored change, which leaves the rows written before that.

    Every payload is cleared, not only the payload of a flag marked for encryption. A stored
    change does not reliably record that marker, and a payload can carry a secret either way,
    so this errs toward clearing too much. It performs no encryption, so it cannot fail on a
    database where the flag payload keys are absent.

    A pending or approved row loses the payload it would have applied. Applying the rest would
    apply something other than what an approver agreed to, so those rows move to `failed` and
    the change has to be submitted again.

    This is a single pass over the rows that exist when it runs. A process still on the previous
    release can write one more plaintext row while the deployment rolls over, and nothing here
    revisits it. The read path keeps such a row's payload out of the API by asking the flag, so
    closing the remaining copy at rest needs this scrub run again once the rollout has drained.
    """
    ChangeRequest = apps.get_model("approvals", "ChangeRequest")

    for change_request in ChangeRequest.objects.filter(resource_type="feature_flag").iterator(chunk_size=500):
        intent, intent_changed = _scrub(change_request.intent or {})
        intent_display, display_changed = _scrub(change_request.intent_display or {})
        if not intent_changed and not display_changed:
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
