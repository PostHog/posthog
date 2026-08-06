import { Properties } from '~/plugin-scaffold'

import { EventWithProperties } from './modality-tokens'

/**
 * Build an `$ai_generation` PluginEvent with a properties bag for cost-pipeline
 * tests. Returns `EventWithProperties` (a `PluginEvent` with non-optional
 * `properties`) so it can be passed to extractors and cost calculators alike.
 */
export function createAIEvent(properties: Properties = {}): EventWithProperties {
    return {
        event: '$ai_generation',
        properties,
        ip: '',
        site_url: '',
        team_id: 0,
        now: '',
        distinct_id: '',
        uuid: '',
        timestamp: '',
    }
}
