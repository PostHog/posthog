import { ProductKey } from '~/queries/schema/schema-general'

import { statusFromProbeDefinitions, type ProbeEventDefinition, type ProductSetupProbe } from './setupProbes'

describe('statusFromProbeDefinitions', () => {
    const probe: ProductSetupProbe = {
        productKey: ProductKey.MCP_ANALYTICS,
        hasDataEvents: ['$mcp_tool_call'],
        waitingEvents: ['$mcp_initialize'],
    }

    const fresh = (name: string): ProbeEventDefinition => ({ name, last_seen_at: new Date().toISOString() })

    // Guards the boot-time seeding for every adopting product: a precedence flip
    // (waiting beating has-data) or a crash on missing counts would either hide
    // the empty state or show it to fully onboarded projects app-wide.
    it.each([
        [['$mcp_tool_call', '$mcp_initialize'], 'has-data'],
        [['$mcp_initialize'], 'waiting-for-data'],
        [[], 'needs-setup'],
    ] as const)('maps definitions %j to %s', (definitions, expected) => {
        expect(statusFromProbeDefinitions(probe, definitions.map(fresh))).toBe(expected)
    })

    it('never reports waiting-for-data for probes without waitingEvents', () => {
        const binaryProbe: ProductSetupProbe = {
            productKey: ProductKey.MCP_ANALYTICS,
            hasDataEvents: ['$exception'],
        }
        expect(statusFromProbeDefinitions(binaryProbe, [fresh('$mcp_initialize')])).toBe('needs-setup')
    })

    // Staleness must cut both ways: a definition from a product abandoned long ago
    // must not hide the setup screen, while an unstamped (`last_seen_at` null)
    // definition must still count as data - it usually means the event just landed.
    it.each([
        ['2020-01-01T00:00:00Z', 'needs-setup'],
        [new Date().toISOString(), 'has-data'],
        [null, 'has-data'],
        // Half a day past the window: whole-day rounding would still read this as fresh.
        [new Date(Date.now() - 90.5 * 24 * 60 * 60 * 1000).toISOString(), 'needs-setup'],
    ] as const)('with staleAfterDays, last_seen_at %s maps to %s', (lastSeenAt, expected) => {
        const staleAwareProbe: ProductSetupProbe = {
            productKey: ProductKey.AI_OBSERVABILITY,
            hasDataEvents: ['$ai_generation'],
            staleAfterDays: 90,
        }
        expect(
            statusFromProbeDefinitions(staleAwareProbe, [{ name: '$ai_generation', last_seen_at: lastSeenAt }])
        ).toBe(expected)
    })

    it('ignores last_seen_at entirely when the probe declares no staleness window', () => {
        expect(
            statusFromProbeDefinitions(probe, [{ name: '$mcp_tool_call', last_seen_at: '2020-01-01T00:00:00Z' }])
        ).toBe('has-data')
    })
})
