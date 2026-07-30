import { ProductKey } from '~/queries/schema/schema-general'

import { statusFromProbeDefinitions, type ProductSetupProbe } from './setupProbes'

describe('statusFromProbeDefinitions', () => {
    const probe: ProductSetupProbe = {
        productKey: ProductKey.MCP_ANALYTICS,
        hasDataEvents: ['$mcp_tool_call'],
        waitingEvents: ['$mcp_initialize'],
    }

    // Guards the boot-time seeding for every adopting product: a precedence flip
    // (waiting beating has-data) or a crash on missing counts would either hide
    // the empty state or show it to fully onboarded projects app-wide.
    it.each([
        [['$mcp_tool_call', '$mcp_initialize'], 'has-data'],
        [['$mcp_initialize'], 'waiting-for-data'],
        [[], 'needs-setup'],
    ] as const)('maps definitions %j to %s', (definitions, expected) => {
        expect(statusFromProbeDefinitions(probe, new Set(definitions))).toBe(expected)
    })

    it('never reports waiting-for-data for probes without waitingEvents', () => {
        const binaryProbe: ProductSetupProbe = {
            productKey: ProductKey.MCP_ANALYTICS,
            hasDataEvents: ['$exception'],
        }
        expect(statusFromProbeDefinitions(binaryProbe, new Set(['$mcp_initialize']))).toBe('needs-setup')
    })
})
