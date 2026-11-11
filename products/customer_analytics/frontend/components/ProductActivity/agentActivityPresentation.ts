import type { AccountAgentActivityResult } from '~/queries/schema/schema-general'

export interface AgentActivitySummary {
    /** Agent calls as a share of agent calls plus app pageviews, or null without any activity. */
    agentShare: number | null
    /** Failed calls as a share of all agent calls, or null without calls. */
    errorRate: number | null
    /** Writes as a share of calls classified as a read or a write, or null without either. */
    writeShare: number | null
}

export function getAgentActivitySummary(result: AccountAgentActivityResult): AgentActivitySummary {
    const { agentCalls, uiPageviews, errors, reads, writes } = result.totals
    const activity = agentCalls + uiPageviews
    return {
        agentShare: activity ? agentCalls / activity : null,
        errorRate: agentCalls ? errors / agentCalls : null,
        writeShare: reads + writes ? writes / (reads + writes) : null,
    }
}

export function formatAgentActivityShare(share: number | null): string {
    return share === null ? '-' : `${Math.round(share * 100)}%`
}

export function getAgentActivityProductLabel(result: AccountAgentActivityResult, productKey: string): string {
    return result.products.find(({ key }) => key === productKey)?.label ?? productKey
}
