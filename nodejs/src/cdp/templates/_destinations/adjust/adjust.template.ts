import { HogFunctionInputSchemaType, HogFunctionTemplate } from '~/cdp/types'

/**
 * Adjust S2S Event Destination
 *
 * Sends server-to-server events to Adjust's S2S API (https://s2s.adjust.com/event).
 * Designed for mobile apps using PostHog's iOS or Android SDKs alongside Adjust.
 *
 * ## Adjust setup
 *
 * 1. Get your **app token** from the Adjust dashboard (App settings > App token).
 * 2. Create **event tokens** for each event type you want to track (Adjust dashboard > Events).
 *    Each mapping below needs its own event token — Adjust identifies events by token, not name.
 *
 * ## Client-side SDK requirements
 *
 * This destination relies on device identifiers captured by PostHog's mobile SDKs.
 * At least one device ID must resolve for events to be accepted by Adjust.
 *
 * ### Auto-captured properties (no extra setup)
 *
 * These are captured automatically by PostHog's iOS and Android SDKs:
 *   - `$device_id`   — a PostHog-generated device identifier (maps to `idfv` by default)
 *   - `$device_type`  — "Mobile", "Tablet", etc.
 *   - `$os`           — "iOS", "Android"
 *   - `$os_version`   — e.g. "17.0"
 *   - `$app_version`  — your app's version string
 *   - `$app_build`    — your app's build number
 *   - `$ip`           — device IP address (forwarded to Adjust for attribution)
 *   - `$raw_user_agent` — device user agent string
 *
 * ### Advertising IDs (require explicit opt-in)
 *
 * IDFA and GAID are NOT captured automatically — they require user consent and
 * additional SDK configuration:
 *
 * **iOS (IDFA):**
 *   PostHog does not capture IDFA by default. To enable it:
 *   1. Add the App Tracking Transparency framework to your app
 *   2. Request tracking permission via ATTrackingManager
 *   3. Once granted, capture the IDFA as a person property:
 *
 *      ```swift
 *      import AdSupport
 *      import AppTrackingTransparency
 *
 *      ATTrackingManager.requestTrackingAuthorization { status in
 *          if status == .authorized {
 *              let idfa = ASIdentifierManager.shared().advertisingIdentifier.uuidString
 *              PostHogSDK.shared.identify("<user-id>", userProperties: [
 *                  "$device_idfa": idfa
 *              ])
 *          }
 *      }
 *      ```
 *
 * **Android (GAID / GPS Ad ID):**
 *   PostHog does not capture the Google Advertising ID by default. To enable it:
 *   1. Add `com.google.android.gms:play-services-ads-identifier` dependency
 *   2. Capture the GAID as a person property:
 *
 *      ```kotlin
 *      import com.google.android.gms.ads.identifier.AdvertisingIdClient
 *
 *      val adInfo = AdvertisingIdClient.getAdvertisingIdInfo(context)
 *      if (!adInfo.isLimitAdTrackingEnabled) {
 *          PostHogAndroid.with(context).identify("<user-id>", mapOf(
 *              "\$android_advertising_id" to adInfo.id
 *          ))
 *      }
 *      ```
 *
 * ### Default device identifier mapping
 *
 * The default `deviceIdentifiers` dictionary maps:
 *   - `idfa`     -> `{person.properties.$device_idfa}`          (iOS advertising ID, requires opt-in)
 *   - `gps_adid` -> `{person.properties.$android_advertising_id}` (Android ad ID, requires opt-in)
 *   - `idfv`     -> `{event.properties.$device_id}`              (auto-captured, works as fallback)
 *
 * Users can customize this mapping to use whatever properties their SDK captures.
 * For example, if you store the Adjust device ID (`adid`) from the Adjust SDK:
 *   - `adid` -> `{person.properties.adjust_device_id}`
 *
 * ### Recommended: capture Adjust device ID client-side
 *
 * If you're running the Adjust SDK alongside PostHog, you can capture Adjust's
 * own device ID (`adid`) and pass it through for the most reliable attribution:
 *
 *   ```swift
 *   // iOS — after Adjust SDK initialization
 *   Adjust.adid { adid in
 *       if let adid = adid {
 *           PostHogSDK.shared.identify("<user-id>", userProperties: [
 *               "adjust_device_id": adid
 *           ])
 *       }
 *   }
 *   ```
 *
 *   Then set `adid` -> `{person.properties.adjust_device_id}` in the device identifiers config.
 */

const buildInputs = (): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'eventToken',
            type: 'string',
            label: 'Event token',
            description:
                'The Adjust event token for this event type. Find event tokens in your Adjust dashboard under Events.',
            default: '',
            secret: false,
            required: true,
        },
        {
            key: 'revenue',
            type: 'string',
            label: 'Revenue',
            description: 'Revenue amount for this event (e.g., 29.99 for a purchase).',
            default: '{toFloat(event.properties.revenue ?? event.properties.value ?? event.properties.price)}',
            secret: false,
            required: false,
        },
        {
            key: 'currency',
            type: 'string',
            label: 'Currency',
            description: 'ISO 4217 currency code for revenue (e.g., USD, EUR). Only used when revenue is set.',
            default: '{event.properties.currency}',
            secret: false,
            required: false,
        },
        {
            key: 'callbackParams',
            type: 'dictionary',
            label: 'Callback parameters',
            description:
                'Custom key-value pairs included as callback parameters. These are forwarded to your callback URL configured in Adjust.',
            default: {},
            secret: false,
            required: false,
        },
        {
            key: 'partnerParams',
            type: 'dictionary',
            label: 'Partner parameters',
            description:
                'Custom key-value pairs included as partner parameters. These are forwarded to your configured network partners.',
            default: {},
            secret: false,
            required: false,
        },
    ]
}

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-adjust',
    name: 'Adjust',
    description: 'Send events to Adjust for mobile attribution',
    icon_url: '/static/services/adjust.png',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
if (empty(inputs.appToken)) {
    throw Error('Adjust app token is required')
}

if (empty(inputs.eventToken)) {
    throw Error('Adjust event token is required')
}

let deviceParams := ''
let hasDeviceId := false
for (let key, value in inputs.deviceIdentifiers) {
    if (not empty(value)) {
        deviceParams := f'{deviceParams}&{encodeURLComponent(key)}={encodeURLComponent(value)}'
        hasDeviceId := true
    }
}

if (not hasDeviceId) {
    throw Error('At least one device identifier is required (idfa, gps_adid, android_id, idfv, or adid)')
}

let body := f's2s=1&app_token={encodeURLComponent(inputs.appToken)}&event_token={encodeURLComponent(inputs.eventToken)}&environment={encodeURLComponent(inputs.environment)}'

body := f'{body}{deviceParams}'

if (not empty(inputs.revenue)) {
    body := f'{body}&revenue={encodeURLComponent(toString(inputs.revenue))}'
    if (not empty(inputs.currency)) {
        body := f'{body}&currency={encodeURLComponent(inputs.currency)}'
    }
}

if (not empty(inputs.callbackParams)) {
    body := f'{body}&callback_params={encodeURLComponent(jsonStringify(inputs.callbackParams))}'
}

if (not empty(inputs.partnerParams)) {
    body := f'{body}&partner_params={encodeURLComponent(jsonStringify(inputs.partnerParams))}'
}

if (not empty(event.properties.$ip)) {
    body := f'{body}&ip_address={encodeURLComponent(event.properties.$ip)}'
}

if (not empty(event.properties.$raw_user_agent)) {
    body := f'{body}&user_agent={encodeURLComponent(event.properties.$raw_user_agent)}'
}

body := f'{body}&created_at_unix={toUnixTimestamp(event.timestamp)}'

let res := fetch('https://s2s.adjust.com/event', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/x-www-form-urlencoded'
    },
    'body': body
})
if (res.status >= 400) {
    throw Error(f'Error from s2s.adjust.com (status {res.status}): {res.body}')
}
`,
    inputs_schema: [
        {
            key: 'appToken',
            type: 'string',
            label: 'App token',
            description: 'Your Adjust app token. Find it in the Adjust dashboard under App settings.',
            secret: true,
            required: true,
        },
        {
            key: 'environment',
            type: 'choice',
            label: 'Environment',
            choices: [
                { label: 'Production', value: 'production' },
                { label: 'Sandbox', value: 'sandbox' },
            ],
            description: 'Set to Sandbox for testing, Production for live traffic.',
            default: 'production',
            secret: false,
            required: true,
        },
        {
            key: 'deviceIdentifiers',
            type: 'dictionary',
            label: 'Device identifiers',
            description:
                'Map of device identifiers to send with events. At least one is required. Keys must match Adjust parameter names: idfa (iOS), gps_adid (Android), android_id, idfv, or adid.',
            default: {
                idfa: '{person.properties.$device_idfa}',
                gps_adid: '{person.properties.$android_advertising_id}',
                idfv: '{event.properties.$device_id}',
            },
            secret: false,
            required: true,
        },
    ],
    mapping_templates: [
        {
            name: 'Application Installed',
            include_by_default: true,
            filters: {
                events: [{ id: 'Application Installed', type: 'events' }],
            },
            inputs_schema: [...buildInputs()],
        },
        {
            name: 'Application Opened',
            include_by_default: true,
            filters: {
                events: [{ id: 'Application Opened', type: 'events' }],
            },
            inputs_schema: [...buildInputs()],
        },
        {
            name: 'Signed Up',
            include_by_default: true,
            filters: {
                events: [{ id: 'Signed Up', type: 'events' }],
            },
            inputs_schema: [...buildInputs()],
        },
        {
            name: 'Order Completed',
            include_by_default: true,
            filters: {
                events: [{ id: 'Order Completed', type: 'events' }],
            },
            inputs_schema: [...buildInputs()],
        },
        {
            name: 'Product Added',
            include_by_default: true,
            filters: {
                events: [{ id: 'Product Added', type: 'events' }],
            },
            inputs_schema: [...buildInputs()],
        },
        {
            name: 'Checkout Started',
            include_by_default: true,
            filters: {
                events: [{ id: 'Checkout Started', type: 'events' }],
            },
            inputs_schema: [...buildInputs()],
        },
    ],
}
