# POSTHOG ENGAGE APP

The Engage PostHog plugin processes and sends customer data and events identified and tracked through Posthog to [Engage](https://engage.so). You can then use the data for customer segmentation, targeted campaigns and automation.

## Tracked Events

The plugin only tracks your **Custom**, **$identify** and **$groupidentify** events. Browser events like button clicks, pageviews are silently ignored.

## Setup

During installation, you will provide your Engage secret key and public key. These are available on the account settings page of your Engage dashboard (Settings -> Account -> API keys). This is used to send your PostHog events to Engage.

Once setup is complete, PostHog will start sending your events to Engage and they will be available on your Engage account.

## Event properties

Extra event properties and metadata are also processed and sent to Engage.

```
posthog.identify(
    '[user unique id]', // distinct_id, required
    { userProperty: 'value1' }, // $set, optional
    { anotherUserProperty: 'value2' } // $set_once, optional
);
```

The example above using the PostHog JS SDK appends extra properties to the identify event. These extra properties will be sent as well to Engage.
