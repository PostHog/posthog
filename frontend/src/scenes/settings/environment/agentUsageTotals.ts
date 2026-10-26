export interface AgentSpendDay {
    day: string
    cost_usd: number
}

export interface AgentSpendTotals {
    todayUsd: number
    monthUsd: number
    windowUsd: number
}

export function agentSpendTotals(days: AgentSpendDay[], todayIso: string): AgentSpendTotals {
    const monthPrefix = todayIso.slice(0, 7)
    return days.reduce<AgentSpendTotals>(
        (totals, { day, cost_usd }) => {
            const dayIso = day.slice(0, 10)
            return {
                todayUsd: totals.todayUsd + (dayIso === todayIso ? cost_usd : 0),
                monthUsd: totals.monthUsd + (dayIso.startsWith(monthPrefix) ? cost_usd : 0),
                windowUsd: totals.windowUsd + cost_usd,
            }
        },
        { todayUsd: 0, monthUsd: 0, windowUsd: 0 }
    )
}
