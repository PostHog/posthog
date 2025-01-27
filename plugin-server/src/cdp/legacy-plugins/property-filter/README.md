# Property Filter Plugin

## Important!

This plugin will only work on events ingested **after** the plugin was enabled. This means all events ingested **before** enabling this plugin will still have the properties.

## Usage

This plugin will remove all specified properties from the event properties object.

Note when specifying `$ip`, additionally `event.ip` will be removed.

## Credits

Heavily inspired by https://github.com/PostHog/first-time-event-tracker