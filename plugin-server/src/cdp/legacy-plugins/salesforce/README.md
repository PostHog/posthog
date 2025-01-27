# Salesforce Plugin

Relay PostHog events to Salesforce

## Config

### V1 config

```
{
            "key": "eventsToInclude",
            "name": "Events to include",
            "type": "string",
            "hint": "Comma separated list of events to include. If not set, no events will be sent"
        },
        {
            "key": "eventPath",
            "name": "Path of the url where events will go to. No leading forward slash",
            "type": "string",
            "required": true
        },
        {
            "key": "eventMethodType",
            "name": "The type of method for the event url",
            "default": "POST",
            "type": "string"
        },
        {
            "key": "propertiesToInclude",
            "name": "Properties to include",
            "type": "string",
            "hint": "Comma separated list of properties to include. If not set, all properties of the event will be sent"
        },
```

Given a list of `eventsToInclude` and `propertiesToInclude`, the plugin will send a request to the `eventPath` using the `eventMethodType` method type.

Only properties on the event that are in the `propertiesToInclude` list will be sent.

### V2 config

```
        {
            "key": "eventEndpointMapping",
            "name": "Event endpoint mapping",
            "type": "json",
            "hint": "⚠️ For advanced uses only ⚠️ Allows you to map events to different SalesForce endpoints. See https://github.com/Vinovest/posthog-salesforce/blob/main/README.md for an example.",
            "default": ""
        },
```

In order to support sending events to different endpoints, you can use the `eventEndpointMapping` config. This config is a JSON object where the keys are the event names and the values are the endpoint paths, method type and properties to include.

For example:

```
eventEndpointMapping: {
    "user signed up": {
        "salesforcePath": "Lead",
        "propertiesToInclude": "name,email,company",
        "method": "POST"
        // SalesForce can be very strict about what fields it accepts
        // you can provide a mapping of PostHog properties to SalesForce fields
        "fieldMappings": {
            email: "Email",
            name: "FullName", 
        }
    }
    "insight analyzed": {
        "salesforcePath": "Engagement",
        "propertiesToInclude": "insight,user,duration",
        "method": "POST"
        // No fieldMappings, so the property names will be used as the field names
        // when fieldMappings are not provided the property names in PostHog will be used
        // these must exactly match the fields expected by SalesForce
    }
}
```

### Setting config

V1 and V2 config cannot be set at the same time.

## Questions?

### [Join the PostHog community.](https://posthog.com/questions)
