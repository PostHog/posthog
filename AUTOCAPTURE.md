# Lifecycle of an autocapture event

An autocapture event originates from 'submit', 'change', and 'click' DOM events
that we set up listeners to
[here](https://github.com/PostHog/posthog-js/blob/master/src/autocapture.js#L223)

A DOM event will result in a PostHog event being send, of the form:

```json
{
    "event": "$autocapture",
    "properties": {
        "$event_type": "click" | "submit" | "change",
        "$ce_version": 1,
        "$elements": [
            ... some kind of array of items that represent DOM nodes along with some of their properties ...
        ],
        ... some list of custom properties
    }
}
```

This is sent to the `/e/` capture endpoint, which then passes it to kafka, which
the plugins-server then picks up.

The plugin server transforms the above to something like:

```json
{
    "event": "$autocapture",
    "properties": {
        "$event_type": "click" | "submit" | "change",
        "$ce_version": 1,
        ... some list of customer properties
    },
    "elementsList": [
        ... some kind of array of items that represent DOM nodes along with some of their properties ...
    ]
}
```

Specifically it:

1.  [deletes `$elements` from
    properties](https://github.com/PostHog/posthog/blob/docs/autocapture-lifecycle/plugin-server/src/worker/ingestion/process-event.ts#L156:L156)
2.  builds an `elementsList`, which is essentially the `$elements` [but truncated
    a
    little](https://github.com/PostHog/posthog/blob/docs/autocapture-lifecycle/plugin-server/src/utils/db/elements-chain.ts#L105:L105)

At some point we send a slightly modified event to a clickhouse ingestion queue [via
`createEvent`](https://github.com/PostHog/posthog/blob/docs/autocapture-lifecycle/plugin-server/src/worker/ingestion/process-event.ts#L195:L195),
which looks something like:

```json
{
    "event": "$autocapture",
    "properties": {
        "$event_type": "click" | "submit" | "change",
        "$ce_version": 1,
        ... some list of customer properties
    },
    "elements_chain": "<some kind of serialization of elementsList>"
}
```

Separately we call `onEvent` with:

1.  the event name
2.  the event properties after `$elements` has been removed

And webhooks with:

1. the event name
2. the event properties after `$elements` has been removed
3. the `elementsList`
