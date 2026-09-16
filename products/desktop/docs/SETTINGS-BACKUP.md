# Back up settings and sounds

The section is behind the `posthog-desktop-settings-backup` feature flag while it rolls out.
When the flag is off, the section and its search entry are hidden.

Open **Settings → Advanced → Back up settings and sounds**.
Choose **Settings and sounds** or **Sounds only**, then select **Export backup** and choose where to save the JSON file.
Copy the file to the other machine and use **Import backup** in the same section.
Review the export version, warnings, and sound previews, then select **Import settings and sounds** or **Import sounds**.
Canceling the file picker or the review leaves your settings unchanged.

Custom sounds are embedded in the file, including their names and audio, so you do not need to copy the original recordings separately.
Both export options include the selected completion sound, volume, and the setting that scales playback with task length.
Import keeps existing custom sounds, skips clips already imported, and preserves both clips when their IDs collide.
It updates the selected sound to use the imported clip's new ID when needed.
Settings missing from a backup keep their current values.

The full backup includes the portable preferences in the main settings store: task and model defaults, notifications, composer behavior, custom instructions, diff display, terminal appearance, and Advanced toggles, plus the theme.
It excludes accounts and API keys, subscription connections, server-managed settings, workspace and repository paths, cached selections tied to a repository, system shortcuts, power settings, and onboarding history.
It also excludes bypass-permissions mode and spend limits, since both are machine-local safety controls that normally require their own explicit confirmation; a backup file cannot enable bypass mode or clear a spend cap on the destination machine.
Custom instruction file syncing stays configured on each machine; the files themselves are not included.
A custom terminal font must also be installed on the destination machine.
The backup is a readable JSON file and includes any text you put in custom instructions.

Backups record the exporting app version and a separate file format version.
Import warns when the app versions differ, skips unavailable settings or unsupported values, and lists invalid sound entries.
A missing or invalid selected clip leaves the destination's current sound selection unchanged.
A newer file format requires an app update before import.
Backups are limited to 64 MB; each custom sound retains the existing 1 MB and 5-second capture limits, with the same allowance for encoder rounding.
A backup can contain at most 1,000 sound entries and 1,000 settings entries, so malformed files cannot produce an unbounded review list.

## Maintaining the format

`packages/core/src/settings/schemas.ts` defines the explicit allowlist and validators for portable settings.
When a preference is added, changed, or removed, update this contract alongside its settings UI and persistence.
Unknown fields and invalid values are skipped individually; missing values are never replaced with defaults.
If a change cannot be represented compatibly, bump the file format version and add a migration before accepting it.
Keep app version metadata independent of the file format version.

The core service owns validation and merging, the UI supplies a store adapter, and Electron supplies native file dialogs and bounded file reads.
Exports write to a temporary sibling file before replacing the destination.
Imports persist settings and audio before publishing them to the live settings store, and serialize the complete update after any pending storage write.
The import preserves edits to unrelated preferences and additions or removals in the sound library while saving.
