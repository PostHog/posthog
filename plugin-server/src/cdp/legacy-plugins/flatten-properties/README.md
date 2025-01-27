# Property Flattener Plugin

> [!WARNING]  
> This plugin has been deprecated. You can use [HogQL](https://posthog.com/docs/hogql) to access nested properties in PostHog.

Flatten nested properties in PostHog events to easily access them in filters.

## Example

For example, if you're an online retailer, and have `purchase` events with the following property structure:

```json
{
    "event": "purchase",
    "properties": {
        "product": {
            "name": "AZ12 shoes",
            "type": "footwear",
            "size": {
                "number": 12,
                "gender": "M"
            }
        }
    }
}
```

This plugin will keep the nested properties unchanged, but also add any nested properties at the first depth, like so:

```json
{
    "event": "purchase",
    "properties": {
        "product": {
            "name": "AZ12 shoes",
            "type": "footwear",
            "size": {
                "number": 12,
                "gender": "M"
            }
        },
        "product__name": "AZ12 shoes",
        "product__type": "footwear",
        "product__size__number": 12,
        "product__size__gender": "M"
    }
}
```

As such, you can now filter your purchase events based on `product__size__number` for example. 

The default separator for nested properties is two subsequent underscores (`__`), but you can also change this to:

* `.`
* `>`
* `/`

When picking your separator, make sure it will not clash with your property naming patterns. 

