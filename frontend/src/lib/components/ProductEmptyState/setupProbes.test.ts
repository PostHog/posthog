import { ProductKey } from '~/queries/schema/schema-general'

import { statusFromProbeDefinitions, type ProductSetupProbe } from './setupProbes'

describe('statusFromProbeDefinitions', () => {
    const probe: ProductSetupProbe = {
        productKey: ProductKey.MCP_ANALYTICS,
        hasDataProperties: ['$mcp_tool_name'],
        waitingProperties: ['$mcp_client_name'],
    }

    // Guards the boot-time seeding for every adopting product: a precedence flip
    // (waiting beating has-data) or a crash on missing counts would either hide
    // the empty state or show it to fully onboarded projects app-wide.
    it.each([
        [['$mcp_tool_name', '$mcp_client_name'], 'has-data'],
        [['$mcp_client_name'], 'waiting-for-data'],
        [[], 'needs-setup'],
    ] as const)('maps definitions %j to %s', (definitions, expected) => {
        expect(statusFromProbeDefinitions(probe, new Set(definitions))).toBe(expected)
    })

    it('never reports waiting-for-data for probes without waitingProperties', () => {
        const binaryProbe: ProductSetupProbe = {
            productKey: ProductKey.MCP_ANALYTICS,
            hasDataProperties: ['$exception_list'],
        }
        expect(statusFromProbeDefinitions(binaryProbe, new Set(['$mcp_client_name']))).toBe('needs-setup')
    })
})
