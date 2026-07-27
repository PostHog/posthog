import { dayjs } from 'lib/dayjs'

import { AnyPropertyFilter } from '~/types'

import { LLMProvider } from '../settings/llmProviderKeysLogic'

/**
 * Pick an hour-vs-day bucket interval for a chart series based on the
 * date-from string. Shared across tagger logics so list/detail/metrics
 * charts all bucket identically.
 */
export function getIntervalFromDateRange(dateFrom: string | null): 'hour' | 'day' {
    if (!dateFrom) {
        return 'day'
    }
    if (dateFrom === 'dStart' || dateFrom === '-0d' || dateFrom === '-0dStart') {
        return 'hour'
    }
    const match = dateFrom.match(/^-(\d+)([hdwmy])/i)
    if (match) {
        const value = parseInt(match[1])
        const unit = match[2].toLowerCase()
        const hoursMap: Record<string, number> = { h: 1, d: 24, w: 168, m: 720, y: 8760 }
        const hours = value * (hoursMap[unit] || 24)
        return hours <= 24 ? 'hour' : 'day'
    }
    const duration = dayjs.duration(dayjs().diff(dayjs(dateFrom)))
    return duration.asDays() <= 1 ? 'hour' : 'day'
}

export interface TagDefinition {
    name: string
    description?: string
}

export type TaggerType = 'llm' | 'hog'

export interface LLMTaggerConfig {
    prompt: string
    tags: TagDefinition[]
    min_tags: number
    max_tags: number | null
}

export interface HogTaggerConfig {
    source: string
    bytecode?: unknown[]
    tags: TagDefinition[]
}

export type TaggerConfig = LLMTaggerConfig | HogTaggerConfig

export interface ModelConfiguration {
    provider: LLMProvider
    model: string
    provider_key_id: string | null
    provider_key_name?: string | null
}

export interface TaggerConditionSet {
    id: string
    rollout_percentage: number
    properties: AnyPropertyFilter[]
}

export interface Tagger {
    id: string
    name: string
    description?: string
    enabled: boolean
    tagger_type: TaggerType
    tagger_config: TaggerConfig
    conditions: TaggerConditionSet[]
    model_configuration: ModelConfiguration | null
    created_at: string
    updated_at: string
    deleted?: boolean
}
