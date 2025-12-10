export interface PlatformMention {
    mentioned: boolean
    position?: number
    cited?: boolean
}

export interface Prompt {
    id: string
    text: string
    category: 'commercial' | 'informational' | 'navigational'
    you_mentioned: boolean
    platforms: {
        chatgpt?: PlatformMention
        perplexity?: PlatformMention
        gemini?: PlatformMention
        claude?: PlatformMention
    }
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
    score_change: number
    score_change_period: 'day' | 'week' | 'month'
    share_of_voice: ShareOfVoice
    mention_rate_over_time: MentionRateDataPoint[]
    prompts: Prompt[]
}
