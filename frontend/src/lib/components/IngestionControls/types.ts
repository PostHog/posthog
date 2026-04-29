import { FeatureFlagBasicType } from '~/types'

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

export interface LinkedFeatureFlag extends Pick<FeatureFlagBasicType, 'id' | 'key'> {
    variant?: string | null
}

export type ErrorTrackingLibrary = 'web'

export interface ErrorTrackingAutoCaptureControls {
    id: string
    library: ErrorTrackingLibrary
    match_type: 'any' | 'all'
    sample_rate: number
    linked_feature_flag: LinkedFeatureFlag | null
    event_triggers: string[]
    url_triggers: UrlTriggerConfig[]
    url_blocklist: UrlTriggerConfig[]
}

// V2: Session Recording Trigger Groups

export type TriggerPropertyFilterOperator =
    | 'exact'
    | 'is_not'
    | 'icontains'
    | 'not_icontains'
    | 'regex'
    | 'not_regex'
    | 'gt'
    | 'lt'

export interface TriggerPropertyFilter {
    key: string
    type: 'event' | 'person'
    operator?: TriggerPropertyFilterOperator
    value?: string | number | boolean | string[]
}

export interface EventTriggerConfig {
    name: string
    properties?: TriggerPropertyFilter[]
}

export interface SessionRecordingTriggerGroup {
    id: string
    name?: string
    sampleRate: number // 0-1
    minDurationMs?: number // 0-30000
    conditions: SessionRecordingTriggerConditions
}

export interface SessionRecordingTriggerConditions {
    matchType: 'any' | 'all'
    events?: (string | EventTriggerConfig)[]
    urls?: UrlTriggerConfig[]
    flag?: string | LinkedFeatureFlag | null
    properties?: TriggerPropertyFilter[]
}

export interface SessionRecordingTriggerGroupsConfig {
    version: 2
    groups: SessionRecordingTriggerGroup[]
}
