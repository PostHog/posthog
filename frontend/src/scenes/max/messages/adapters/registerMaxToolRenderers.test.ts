// Importing the module runs its side effect: registering Max's product-specific tool renderers into the
// shared toolRegistry. We assert the stable key → displayName metadata it contributes (the lazy
// Renderer itself is an opaque chunk).
import './registerMaxToolRenderers'

import { toolRegistry } from 'products/posthog_ai/frontend/api/tools'

describe('registerMaxToolRenderers', () => {
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
