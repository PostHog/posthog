from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

# Based off of https://customer.io/docs/api/track/#operation/entity

template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    type="transformation",
    id="template-downsample",
    name="Downsample",
    description="Downsample events to a percentage of the original",
    icon_url="/static/hedgehog/builder-hog-01.png",
    category=["Custom"],
    hog="""
    let shouldIngestEvent := true

    let percentage := inputs.percentage
    let floatPercentage := percentage / 100
    let samplingMethod := inputs.samplingMethod

        if (percentage > 100 or percentage < 0) {
        throw Error('Percentage must be a number between 0 and 100.')
    }

    if (samplingMethod == 'random') {
        shouldIngestEvent := randCanonical() <= floatPercentage
    } else{
        let hash := sha256Hex(event.distinct_id)
        // Extract the first 8 characters of the hash
        let hashPrefix := substring(hash, 0, 8)
        // Convert the hex substring to an integer
        let hashInt := parseInt(hashPrefix, 16)
        // Determine if the event should be ingested based on the sampling percentage
        shouldIngestEvent := (hashInt % 100) < percentage
    }

    return shouldIngestEvent ? event : null
    """.strip(),
    inputs_schema=[
        {
            "key": "percentage",
            "type": "number",
            "label": "Percentage",
            "description": "Reduces events flowing in to the percentage value above",
            "default": 100,
            "secret": False,
            "required": True,
        },
        {
            "key": "samplingMethod",
            "type": "choice",
            "label": "Sampling method",
            "description": "Random sampling will sample events randomly, while distinct ID aware sampling will sample based on distinct IDs, meaning that a user's events will all be ingested or all be dropped at a given sample percentage.",
            "choices": [
                {"label": "Random sampling", "value": "random"},
                {"label": "Distinct ID aware sampling", "value": "distinct_id"},
            ],
            "default": "random",
            "required": True,
        },
    ],
)
