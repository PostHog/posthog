# Migrating legacy destinations to hog functions

A legacy `onEvent` plugin runs from a `PluginConfig` row. `CdpLegacyEventsConsumer` reads those rows and
synthesises a throwaway hog function for each one, so the destination has no real row, no UI, and no way off
the plugin tables.

A `legacy_destination` hog function replaces that. It runs the same bundled processor, still inline in
`CdpLegacyEventsConsumer`, never on a cyclotron worker.

## How the consumer picks

The consumer reads both representations and prefers the hog function for a matching `(team_id, template_id)`.
The plugin config stays enabled the whole time, so only one of the pair ever runs and rollback is deleting the
hog function rather than restoring anything.

Two rules follow from that, and both have bitten:

- Only an **enabled** hog function supersedes. Disable one and the plugin config runs again, so the
  destinations list has to show it again too.
- Nothing in the database stops two migrated rows sharing a template. The consumer keeps the oldest and
  ignores the rest, so a duplicate cannot send every event twice.

## Rolling it out

```bash
# 1. See what would happen. Reports the inputs it would drop, per config.
python manage.py migrate_legacy_destinations_to_hog_functions --dry-run

# 2. Create the hog functions. Plugin configs are left enabled.
python manage.py migrate_legacy_destinations_to_hog_functions

# 3. Once the migrated rows look right, turn off the configs they replaced.
python manage.py migrate_legacy_destinations_to_hog_functions --disable-migrated
```

Step 3 only touches a config an enabled `legacy_destination` already covers, so running it early does nothing.

Scope any step with `--team-ids` or `--plugin-config-ids`. `--strict-inputs` refuses a config carrying inputs
the template schema does not declare, instead of dropping them.

## Watching it

`cdp_legacy_event_consumer_execution_result_total` carries a `source` label of `plugin_config` or
`hog_function`.

```promql
# Did the swap happen, and how far along is it?
sum by (source) (rate(cdp_legacy_event_consumer_execution_result_total[5m]))

# Did anything break? This should not move across the cutover.
sum by (result) (rate(cdp_legacy_event_consumer_execution_result_total[5m]))
```

Every execution increments exactly once, so a steady total while the split moves is also the evidence that
nothing runs twice or gets dropped.

App metrics keep each representation's own identity: an unmigrated config reports under `legacy_plugin` with
its numeric id, a migrated row under `hog_function` with its own id. A destination's metric history therefore
splits at the cutover rather than carrying over.

## What the migration refuses

- A plugin with no bundled template.
- A **required** input with no value. One of these saves cleanly and then fails at runtime with no
  credentials, so it is refused rather than migrated.

Inputs the template schema does not declare are dropped and reported, because no bundled processor reads them.

## What this does not remove

`posthog_pluginstorage` stays. The `first-time-event-tracker` transformation answers "is this the first time
this event was ever seen", which no event or person property carries, and it reaches that state through a
numeric plugin config id. Its `PluginConfig` rows therefore have to survive as foreign key anchors even
though they are disabled, and deleting them would silently make every event report as first-ever.
