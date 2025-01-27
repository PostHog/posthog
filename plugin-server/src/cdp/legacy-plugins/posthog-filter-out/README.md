# 🦔 PostHog Filter Out Plugin

> Ingest only those events satisfying the given filter conditions.

## Configuration

This plugin configuration requires a JSON file containing an array of filter groups. Events matching **any** filter group will be kept, meaning there's an OR logic between groups. However, within each filter group, **all** conditions must be met (AND logic).

**Example Filters:**

**1. Single Filter Group:**  
To keep events where all the following conditions are met:
- **Email** _does not contain_ **yourcompany.com**
- **Host** _is not_ **localhost:8000**
- **Browser version** _is greater than_ **100**

```json
[
  [
    {
      "property": "email",
      "type": "string",
      "operator": "not_contains",
      "value": "yourcompany.com"
    },
    {
      "property": "$host",
      "type": "string",
      "operator": "is_not",
      "value": "localhost:8000"
    },
    {
      "property": "$browser_version",
      "type": "number",
      "operator": "gt",
      "value": 100
    }
  ]
]
```

**2. Multiple Filter Groups (OR Logic):**  
To keep events where:
- **Group 1:** **Email** _does not contain_ **yourcompany.com** and **Host** _is not_ **localhost:8000**  
- OR
- **Group 2:** **Event Type** _is_ **signup** and **Browser** _is_ **Chrome**

```json
[
  [
    {
      "property": "email",
      "type": "string",
      "operator": "not_contains",
      "value": "yourcompany.com"
    },
    {
      "property": "$host",
      "type": "string",
      "operator": "is_not",
      "value": "localhost:8000"
    }
  ],
  [
    {
      "property": "$event_type",
      "type": "string",
      "operator": "is",
      "value": "signup"
    },
    {
      "property": "$browser",
      "type": "string",
      "operator": "is",
      "value": "Chrome"
    }
  ]
]
```

In this configuration, an event will be retained if it matches **any** of the specified groups.

### Allowed Types and Their Operators

| Type    | Operators                                            |
| ------- | ---------------------------------------------------- |
| number  | gt, gte, lt, lte, eq, neq                            |
| string  | is, is_not, contains, not_contains, regex, not_regex |
| boolean | is, is_not                                           |

## License

[MIT](LICENSE)