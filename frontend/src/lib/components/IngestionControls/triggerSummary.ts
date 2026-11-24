import { match } from 'ts-pattern'

import { pluralize } from 'lib/utils/strings'

import { Trigger, TriggerType } from './types'

export const summaryLabel: Record<TriggerType, string> = {
    [TriggerType.URL_MATCH]: 'URL matching',
    [TriggerType.EVENT]: 'Event triggers',
    [TriggerType.FEATURE_FLAG]: 'Feature flag',
    [TriggerType.SAMPLING]: 'Sampling rate',
    [TriggerType.MIN_DURATION]: 'Minimum duration',
    [TriggerType.URL_BLOCKLIST]: 'URL blocklist',
}

export function triggerSummary(trigger: Trigger): string | null {
    return match(trigger)
        .with({ type: TriggerType.URL_MATCH }, (t) => pluralize(t.urls?.length || 0, 'pattern'))
        .with({ type: TriggerType.EVENT }, (t) => pluralize(t.events?.length || 0, 'event'))
        .with({ type: TriggerType.FEATURE_FLAG }, (t) => t.key)
        .with({ type: TriggerType.SAMPLING }, (t) => (t.sampleRate ? `${t.sampleRate * 100}%` : 'N/A'))
        .with({ type: TriggerType.MIN_DURATION }, (t) => (t.minDurationMs ? `${t.minDurationMs / 1000}s` : 'N/A'))
        .with({ type: TriggerType.URL_BLOCKLIST }, (t) => pluralize(t.urls?.length || 0, 'pattern'))
        .run()
}
