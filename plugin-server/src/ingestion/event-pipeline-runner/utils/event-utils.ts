import { Counter } from 'prom-client'

import { Element, PipelineEvent, PluginEvent, Properties } from '../../../types'
import { hasDifferenceWithProposedNewNormalisationMode, personInitialAndUTMProperties, sanitizeString } from './utils'

// Values of the $lib property that have been seen in the wild
const KNOWN_LIB_VALUES = new Set([
    'web',
    'posthog-python',
    '',
    'js',
    'posthog-node',
    'posthog-react-native',
    'posthog-ruby',
    'posthog-ios',
    'posthog-android',
    'Segment',
    'posthog-go',
    'analytics-node',
    'RudderLabs JavaScript SDK',
    'mobile',
    'posthog-php',
    'zapier',
    'Webflow',
    'posthog-flutter',
    'com.rudderstack.android.sdk.core',
    'rudder-analytics-python',
    'rudder-ios-library',
    'rudder-analytics-php',
    'macos',
    'service_data',
    'flow',
    'PROD',
    'unknown',
    'api',
    'unbounce',
    'backend',
    'analytics-python',
    'windows',
    'cf-analytics-go',
    'server',
    'core',
    'Marketing',
    'Product',
    'com.rudderstack.android.sdk',
    'net-gibraltar',
    'posthog-java',
    'rudderanalytics-ruby',
    'GSHEETS_AIRBYTE',
    'posthog-plugin-server',
    'DotPostHog',
    'analytics-go',
    'serverless',
    'wordpress',
    'hog_function',
    'http',
    'desktop',
    'elixir',
    'DEV',
    'RudderAnalytics.NET',
    'PR',
    'railway',
    'HTTP',
    'extension',
    'cyclotron-testing',
    'RudderStack Shopify Cloud',
    'GSHEETS_MONITOR',
    'Rudder',
    'API',
    'rudder-sdk-ruby-sync',
    'curl',
])

const getKnownLibValueOrSentinel = (lib: string): string => {
    if (lib === '') {
        return '$empty'
    }
    if (!lib) {
        return '$nil'
    }
    if (KNOWN_LIB_VALUES.has(lib)) {
        return lib
    }
    return '$other'
}

export function getElementsChain(properties: Properties): string {
    /*
        We're deprecating $elements in favor of $elements_chain, which doesn't require extra
        processing on the ingestion side and is the way we store elements in ClickHouse.
        As part of that we'll move posthog-js to send us $elements_chain as string directly,
        but we still need to support the old way of sending $elements and converting them
        to $elements_chain, while everyone hasn't upgraded.
        */
    let elementsChain = ''
    if (properties['$elements_chain']) {
        elementsChain = properties['$elements_chain']
        // elementsOrElementsChainCounter.labels('elements_chain').inc()
    } else if (properties['$elements']) {
        const elements: Record<string, any>[] | undefined = properties['$elements']
        let elementsList: Element[] = []
        if (elements && elements.length) {
            elementsList = extractElements(elements)
            elementsChain = elementsToString(elementsList)
        }
        // elementsOrElementsChainCounter.labels('elements').inc()
    }
    delete properties['$elements_chain']
    delete properties['$elements']
    return elementsChain
}

const DIFFERENCE_WITH_PROPOSED_NORMALISATION_MODE_COUNTER = new Counter({
    name: 'difference_with_proposed_normalisation_mode',
    help: 'Counter for events that would give a different result with the new proposed normalisation mode',
    labelNames: ['library'],
})
/// Does normalization steps involving the $process_person_profile property. This is currently a separate
/// function because `normalizeEvent` is called from multiple places, some early in the pipeline,
/// and we want to have one trusted place where `$process_person_profile` is handled and passed through
/// all of the processing steps.
///
/// If `formPipelineEvent` is removed this can easily be combined with `normalizeEvent`.
export function normalizeProcessPerson(event: PluginEvent, processPerson: boolean): PluginEvent {
    const properties = event.properties ?? {}

    if (!processPerson || event.event === '$groupidentify') {
        delete event.$set
        delete event.$set_once
        // In an abundance of caution and future proofing, we delete the $unset field from the
        // event if it is set. As of this writing we only *read* $unset out of `properties`, but
        // we may as well future-proof this code path.
        delete (event as any)['$unset']
        delete properties.$set
        delete properties.$set_once
        delete properties.$unset
    }

    if (!processPerson) {
        // Recorded for clarity and so that the property exists if it is ever sent elsewhere,
        // e.g. for migrations.
        properties.$process_person_profile = false
    } else {
        // Removed as it is the default, note that we have record the `person_mode` column
        // in ClickHouse for all events.
        delete properties.$process_person_profile
    }

    event.properties = properties
    return event
}

export function normalizeEvent<T extends PipelineEvent | PluginEvent>(event: T): T {
    event.distinct_id = sanitizeString(String(event.distinct_id))

    let properties = event.properties ?? {}
    if (event['$set']) {
        properties['$set'] = { ...properties['$set'], ...event['$set'] }
    }
    if (event['$set_once']) {
        properties['$set_once'] = { ...properties['$set_once'], ...event['$set_once'] }
    }
    if (!properties['$ip'] && event.ip) {
        // if $ip wasn't sent with the event, then add what we got from capture
        properties['$ip'] = event.ip
    }
    // For safety while PluginEvent still has an `ip` field
    event.ip = null

    if (hasDifferenceWithProposedNewNormalisationMode(properties)) {
        DIFFERENCE_WITH_PROPOSED_NORMALISATION_MODE_COUNTER.labels({
            library: getKnownLibValueOrSentinel(properties['$lib']),
        }).inc()
    }

    if (!['$snapshot', '$performance_event'].includes(event.event)) {
        properties = personInitialAndUTMProperties(properties)
    }
    if (event.sent_at) {
        properties['$sent_at'] = event.sent_at
    }

    event.properties = properties
    return event
}

function escapeQuotes(input: string): string {
    return input.replace(/"/g, '\\"')
}

export function elementsToString(elements: Element[]): string {
    const ret = elements.map((element) => {
        let el_string = ''
        if (element.tag_name) {
            el_string += element.tag_name
        }
        if (element.attr_class) {
            element.attr_class.sort()
            for (const single_class of element.attr_class) {
                el_string += `.${single_class.replace(/"/g, '')}`
            }
        }
        let attributes: Record<string, any> = {
            ...(element.text ? { text: element.text } : {}),
            'nth-child': element.nth_child ?? 0,
            'nth-of-type': element.nth_of_type ?? 0,
            ...(element.href ? { href: element.href } : {}),
            ...(element.attr_id ? { attr_id: element.attr_id } : {}),
            ...element.attributes,
        }
        attributes = Object.fromEntries(
            Object.entries(attributes)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([key, value]) => [escapeQuotes(key.toString()), escapeQuotes(value.toString())])
        )
        el_string += ':'
        el_string += Object.entries(attributes)
            .map(([key, value]) => `${key}="${value}"`)
            .join('')
        return el_string
    })
    return ret.join(';')
}

export function extractElements(elements: Array<Record<string, any>>): Element[] {
    return elements.map((el) => ({
        text: el['$el_text']?.slice(0, 400),
        tag_name: el['tag_name'],
        href: el['attr__href']?.slice(0, 2048),
        attr_class: extractAttrClass(el),
        attr_id: el['attr__id'],
        nth_child: el['nth_child'],
        nth_of_type: el['nth_of_type'],
        attributes: Object.fromEntries(Object.entries(el).filter(([key]) => key.startsWith('attr__'))),
    }))
}

function extractAttrClass(el: Record<string, any>): Element['attr_class'] {
    const attr_class = el['attr__class']
    if (!attr_class) {
        return undefined
    } else if (Array.isArray(attr_class)) {
        return attr_class
    } else {
        return attr_class.split(' ')
    }
}
