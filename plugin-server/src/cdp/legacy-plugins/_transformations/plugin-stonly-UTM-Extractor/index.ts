import { URL } from 'url'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

// Processes each event, optionally transforming it

const extractUtmFromUrl = (urlString: string, utm: string) => {
    const url = new URL(urlString)
    return url.searchParams.get(utm)
}

const utmProperties = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term']

const urlProperties = ['current_url', '$current_url', 'signUpPageConversion', 'signUpPageLanding', 'firstPageViewed']

export function processEvent(event: PluginEvent, _: LegacyTransformationPluginMeta) {
    // Some events (such as $identify) don't have properties
    let didAddUtms = false
    if (event.properties) {
        for (const urlProp of urlProperties) {
            if (event.properties[urlProp] !== undefined && event.properties[urlProp].includes('utm')) {
                for (const utmProp of utmProperties) {
                    // Only change events that have an URL and no UTMs set (mostly segment)
                    if (!event.properties[utmProp]) {
                        const extractedUtm = extractUtmFromUrl(event.properties[urlProp], utmProp)
                        if (extractedUtm) {
                            event.properties[utmProp] = extractedUtm
                            didAddUtms = true
                        }
                    }
                }
            }
            // Only take UTMS from the first available URL, then return
            if (didAddUtms) {
                return event
            }
        }
    }
    // Return the event to be ingested, or return null to discard
    return event
}
