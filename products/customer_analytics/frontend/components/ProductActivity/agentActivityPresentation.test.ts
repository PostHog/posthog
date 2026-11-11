import type { AccountAgentActivityResult } from '~/queries/schema/schema-general'

import { formatAgentActivityShare, getAgentActivitySummary } from './agentActivityPresentation'

function resultWith(totals: Partial<AccountAgentActivityResult['totals']>): AccountAgentActivityResult {
    return {
        columns: [],
        buckets: [],
        products: [],
        tools: [],
        clients: [],
        intents: [],
        truncated: false,
        totals: {
            agentCalls: 0,
            agentPeople: 0,
            conversations: 0,
            errors: 0,
            reads: 0,
            writes: 0,
            uiPageviews: 0,
            ...totals,
        },
    }
}

describe('agentActivityPresentation', () => {
    it.each([
        ['no activity', {}, ['-', '-', '-']],
        [
            'agents and the app',
            { agentCalls: 30, uiPageviews: 90, errors: 3, reads: 20, writes: 5 },
            ['25%', '10%', '20%'],
        ],
        ['agents only, with calls nobody classified', { agentCalls: 4 }, ['100%', '0%', '-']],
    ])('summarises %s', (_, totals, expected) => {
        const summary = getAgentActivitySummary(resultWith(totals))
        expect([summary.agentShare, summary.errorRate, summary.writeShare].map(formatAgentActivityShare)).toEqual(
            expected
        )
    })
})
