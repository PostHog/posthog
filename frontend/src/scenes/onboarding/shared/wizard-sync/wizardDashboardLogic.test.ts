import { pickWizardDashboard } from './wizardDashboardLogic'

// The run started at 00:10; the skew window reaches back to 00:08.
const STARTED_AT = '2026-01-01T00:10:00Z'

function dash(
    overrides: Partial<Parameters<typeof pickWizardDashboard>[0][number]> = {}
): Parameters<typeof pickWizardDashboard>[0][number] {
    return {
        id: 1,
        name: 'Product analytics',
        created_at: '2026-01-01T00:15:00Z',
        deleted: false,
        creation_mode: 'default',
        ...overrides,
    }
}

describe('pickWizardDashboard', () => {
    it.each([
        // Wrongly matching here surfaces a "See your dashboard" CTA pointing at somebody's
        // pre-existing or template dashboard — worse than showing nothing.
        ['created during the run', [dash()], 1],
        ['created before the run', [dash({ created_at: '2026-01-01T00:00:00Z' })], null],
        ['created within the clock-skew window', [dash({ created_at: '2026-01-01T00:09:00Z' })], 1],
        ['a template dashboard', [dash({ creation_mode: 'template' })], null],
        ['a deleted dashboard', [dash({ deleted: true })], null],
        ['an unparseable created_at', [dash({ created_at: 'not-a-date' })], null],
        [
            'multiple matches → newest wins',
            [dash({ id: 1, created_at: '2026-01-01T00:12:00Z' }), dash({ id: 2, created_at: '2026-01-01T00:20:00Z' })],
            2,
        ],
        ['no dashboards at all', [], null],
    ])('%s', (_name, dashboards, expectedId) => {
        const result = pickWizardDashboard(dashboards, STARTED_AT)
        expect(result?.id ?? null).toBe(expectedId)
    })

    it('returns null when the run start time is unparseable', () => {
        expect(pickWizardDashboard([dash()], 'not-a-date')).toBeNull()
    })
})
