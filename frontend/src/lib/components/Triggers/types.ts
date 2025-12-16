export type Trigger =
    | URLMatchTrigger
    | EventTrigger
    | FeatureFlagTrigger
    | SamplingTrigger
    | MinDurationTrigger
    | UrlBlocklistTrigger

export enum TriggerType {
    URL_MATCH = 'url_match',
    EVENT = 'event',
    FEATURE_FLAG = 'feature_flag',
    SAMPLING = 'sampling',
    MIN_DURATION = 'min_duration',
    URL_BLOCKLIST = 'url_blocklist',
}

export interface URLMatchTrigger extends BaseTrigger {
    type: TriggerType.URL_MATCH
    urls: UrlTriggerConfig[] | null
}

export interface EventTrigger extends BaseTrigger {
    type: TriggerType.EVENT
    events: string[] | null
}

export interface FeatureFlagTrigger extends BaseTrigger {
    type: TriggerType.FEATURE_FLAG
    key: string | null
}

export interface SamplingTrigger extends BaseTrigger {
    type: TriggerType.SAMPLING
    sampleRate: number | null
}

export interface MinDurationTrigger extends BaseTrigger {
    type: TriggerType.MIN_DURATION
    minDurationMs: number | null
}

export interface UrlBlocklistTrigger extends BaseTrigger {
    type: TriggerType.URL_BLOCKLIST
    urls: UrlTriggerConfig[] | null
}

interface BaseTrigger {
    type: TriggerType
    enabled: boolean
}

export type UrlTriggerConfig = {
    url: string
    matching: 'regex'
}
