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


# class TemplateCustomerioMigrator(HogFunctionTemplateMigrator):
#     plugin_url = "https://github.com/PostHog/customerio-plugin"

#     @classmethod
#     def migrate(cls, obj):
#         hf = deepcopy(dataclasses.asdict(template))

#         host = obj.config.get("host", "track.customer.io")
#         events_to_send = obj.config.get("eventsToSend")
#         token = obj.config.get("customerioToken", "")
#         customerio_site_id = obj.config.get("customerioSiteId", "")
#         anon_option = obj.config.get("sendEventsFromAnonymousUsers", "Send all events")
#         identify_by_email = obj.config.get("identifyByEmail", "No") == "Yes"

#         hf["filters"] = {}

#         if anon_option == "Send all events":
#             pass
#         elif anon_option == "Only send events from users with emails":
#             # TODO: Add support for general filters
#             hf["filters"]["properties"] = [
#                 {
#                     "key": "email",
#                     "value": "is_set",
#                     "operator": "is_set",
#                     "type": "person",
#                 }
#             ]
#         elif anon_option == "Only send events from users that have been identified":
#             hf["filters"]["properties"] = [
#                 {
#                     "key": "$is_identified",
#                     "value": ["true"],
#                     "operator": "exact",
#                     "type": "event",
#                 }
#             ]

#         if events_to_send:
#             hf["filters"]["events"] = [
#                 {"id": event.strip(), "name": event.strip() or "All events", "type": "events", "order": 0}
#                 for event in events_to_send.split(",")
#             ]

#         hf["inputs"] = {
#             "action": {"value": "automatic"},
#             "site_id": {"value": customerio_site_id},
#             "token": {"value": token},
#             "host": {"value": host},
#             "identifiers": {"value": {"email": "{person.properties.email}"}}
#             if identify_by_email
#             else {"value": {"id": "{event.distinct_id}"}},
#             "include_all_properties": {"value": True},
#             "attributes": {"value": {}},
#         }

#         return hf


# import { PluginEvent, PluginMeta } from '@posthog/plugin-scaffold'
# import { createHash } from 'crypto'

# export function setupPlugin({ config, global }: PluginMeta) {
#     const percentage = parseFloat(config.percentage)
#     if (isNaN(percentage) || percentage > 100 || percentage < 0) {
#         throw new Error('Percentage must be a number between 0 and 100.')
#     }
#     global.percentage = percentage
#     global.randomSampling = config.samplingMethod === 'Random sampling'
# }

# // /* Runs on every event */
# export function processEvent(event: PluginEvent, { global }: PluginMeta) {

#     // hash is a sha256 hash of the distinct_id represented in base 16
#     // We take the first 15 digits, convert this into an integer,
#     // dividing by the biggest 15 digit, base 16 number to get a value between 0 and 1.
#     // This is stable, so a distinct_id that was allowed before will continue to be allowed,
#     // even if the percentage increases


#     let shouldIngestEvent = true
#     if (global.randomSampling) {
#         shouldIngestEvent = parseInt(Math.random()*100) <= global.percentage
#     } else {
#         const hash = createHash("sha256")
#             .update(event.distinct_id)
#             .digest("hex")
#         const decisionValue = parseInt(hash.substring(0, 15), 16) / 0xfffffffffffffff
#         shouldIngestEvent = decisionValue <= global.percentage / 100
#     }

#     if (shouldIngestEvent) {
#         return event
#     }
#     return null
# }
