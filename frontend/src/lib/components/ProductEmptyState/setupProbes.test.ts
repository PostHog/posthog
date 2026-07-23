import { ProductKey } from '~/queries/schema/schema-general'

import { statusFromProbeCounts, type ProductSetupProbe } from './setupProbes'

describe('statusFromProbeCounts', () => {
    const probe: ProductSetupProbe = {
        productKey: ProductKey.MCP_ANALYTICS,
        hasDataEvents: ['$mcp_tool_call'],
        waitingEvents: ['$mcp_initialize'],
    }

    // Guards the boot-time seeding for every adopting product: a precedence flip
    // (waiting beating has-data) or a crash on missing counts would either hide
    // the empty state or show it to fully onboarded projects app-wide.
    it.each([
        [{ $mcp_tool_call: 5, $mcp_initialize: 2 }, 'has-data'],
        [{ $mcp_initialize: 2 }, 'waiting-for-data'],
        [{}, 'needs-setup'],
        [{ $mcp_tool_call: 0, $mcp_initialize: 0 }, 'needs-setup'],
    ] as const)('maps counts %j to %s', (counts, expected) => {
        expect(statusFromProbeCounts(probe, counts as Record<string, number>)).toBe(expected)
    })

    it('never reports waiting-for-data for probes without waitingEvents', () => {
        const binaryProbe: ProductSetupProbe = { productKey: ProductKey.MCP_ANALYTICS, hasDataEvents: ['$exception'] }
        expect(statusFromProbeCounts(binaryProbe, { $mcp_initialize: 10 })).toBe('needs-setup')
    })
})
