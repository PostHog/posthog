export interface PlatformMention {
    mentioned: boolean
    position?: number | null
    cited?: boolean | null
}

export interface Competitor {
    name: string
    domain?: string | null
    logo_url?: string | null
}

export interface Prompt {
    id: string
    text: string
    topic: string // The category/topic this prompt belongs to (e.g., "Self-hosted Analytics")
    category: 'commercial' | 'informational' | 'navigational'
    you_mentioned: boolean
    platforms: {
        openai?: PlatformMention
        chatgpt?: PlatformMention
        perplexity?: PlatformMention
        gemini?: PlatformMention
        claude?: PlatformMention
    }
    competitors?: Competitor[]
    competitors_mentioned: string[]
    last_checked: string
}

export interface MentionRateDataPoint {
    date: string
    you: number
    [competitor: string]: number | string
}

export interface ShareOfVoice {
    you: number
    competitors: Record<string, number>
}

export interface DashboardData {
    visibility_score: number
    score_change?: number
    score_change_period?: 'day' | 'week' | 'month'
    share_of_voice: ShareOfVoice
    mention_rate_over_time?: MentionRateDataPoint[]
    prompts: Prompt[]
}

// Derived types for dashboard views
export interface Topic {
    name: string
    promptCount: number
    visibility: number
    relevancy: number
    avgRank: number
    citations: number
    topCompetitors: { name: string; icon?: string }[]
    prompts: Prompt[]
}

export interface CompetitorComparison {
    competitor: string
    sharedPrompts: number
    youLeadPercentage: number
    youLeadsIn: { topic: string; percentage: number }[]
    theyLeadIn: { topic: string; percentage: number }[]
}

export interface MatrixCell {
    topic: string
    competitor: string
    visibility: number
    avgRank: number | null
}

export interface TopCitedSource {
    domain: string
    responseCount: number
}
