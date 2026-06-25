// Importing the module runs its side effect: registering Max's product-specific tool renderers into the
// shared toolRegistry. We assert the stable key → displayName metadata it contributes (the lazy
// Renderer itself is an opaque chunk).
import './registerMaxToolRenderers'

import { registerToolRenderers, toolRegistry, type ToolRegistryEntry } from 'products/posthog_ai/frontend/api/tools'

describe('registerMaxToolRenderers', () => {
    it('registerToolRenderers bulk-registers every entry it is handed', () => {
        const Renderer = (() => null) as unknown as ToolRegistryEntry['Renderer']
        const icon = null as unknown as JSX.Element
        registerToolRenderers([
            { key: '__test_alpha__', displayName: 'Alpha', icon, Renderer },
            { key: '__test_beta__', displayName: 'Beta', icon, Renderer },
        ])
        expect(toolRegistry.lookup('__test_alpha__')?.displayName).toEqual('Alpha')
        expect(toolRegistry.lookup('__test_beta__')?.displayName).toEqual('Beta')
    })

    it.each([
        ['insight-create', 'Insight'],
        ['insight-update', 'Insight'],
        ['insight-get', 'Insight'],
        ['create_insight', 'Insight'],
        ['dashboard-create', 'Dashboard'],
        ['upsert_dashboard', 'Dashboard'],
        ['query-session-recordings-list', 'Session recordings'],
        ['search_session_recordings', 'Session recordings'],
        ['query-error-tracking-issues-list', 'Error tracking'],
        ['search_error_tracking_issues', 'Error tracking'],
        ['query-trends', 'Trends query'],
        ['query-funnel', 'Funnel query'],
        ['notebooks-create', 'Notebook'],
        ['notebook-edit', 'Notebook'],
    ])('registers %s into the shared registry with displayName "%s"', (key, displayName) => {
        const entry = toolRegistry.lookup(key)
        expect(entry).not.toBeNull()
        expect(entry?.displayName).toEqual(displayName)
    })
})
