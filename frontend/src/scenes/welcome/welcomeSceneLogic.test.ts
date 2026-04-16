import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { welcomeSceneLogic } from './welcomeSceneLogic'

describe('welcomeSceneLogic', () => {
    let logic: ReturnType<typeof welcomeSceneLogic.build>

    const mockPayload = {
        organization_name: 'Acme Inc',
        inviter: { name: 'Alex', email: 'alex@acme.com' },
        team_members: [{ name: 'Alex', email: 'alex@acme.com', avatar: null, role: 'Owner', last_active: 'today' }],
        recent_activity: [
            {
                type: 'Insight.created',
                actor_name: 'Alex',
                entity_name: 'Signups by day',
                entity_url: '/project/1/insights/abc',
                timestamp: '2026-04-01T12:00:00Z',
            },
        ],
        popular_dashboards: [
            {
                id: 42,
                name: 'Product overview',
                description: 'Signups + revenue',
                team_id: 1,
                url: '/project/1/dashboard/42',
            },
        ],
        products_in_use: ['product_analytics', 'feature_flags'],
        suggested_next_steps: [
            { label: 'See active feature flags', href: '/feature_flags', reason: 'Your team uses Feature flags' },
        ],
        is_organization_first_user: false,
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/@current/welcome/': mockPayload,
            },
            post: {
                '/api/users/@me/welcome_screen/dismiss/': { welcome_screen_seen_at: '2026-04-16T12:00:00Z' },
            },
        })
        initKeaTests()
        logic = welcomeSceneLogic()
        logic.mount()
    })

    it('loads welcome data on mount', async () => {
        await expectLogic(logic).toDispatchActions(['loadWelcomeData', 'loadWelcomeDataSuccess'])
        expect(logic.values.welcomeData.organization_name).toBe('Acme Inc')
        expect(logic.values.organizationName).toBe('Acme Inc')
    })

    it('exposes popular dashboards as primary cta href', async () => {
        await expectLogic(logic).toDispatchActions(['loadWelcomeDataSuccess'])
        expect(logic.values.primaryCtaHref).toBe('/project/1/dashboard/42')
        expect(logic.values.primaryCtaLabel).toContain('Product overview')
    })

    it('renders default cta when there are no dashboards', async () => {
        useMocks({
            get: {
                '/api/organizations/@current/welcome/': { ...mockPayload, popular_dashboards: [] },
            },
        })
        logic.unmount()
        logic = welcomeSceneLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWelcomeDataSuccess'])
        expect(logic.values.primaryCtaHref).toBe('/')
        expect(logic.values.primaryCtaLabel).toBe('Take me to the project home')
    })

    it('tracks card interactions', async () => {
        await expectLogic(logic).toDispatchActions(['loadWelcomeDataSuccess'])
        logic.actions.trackCardClick('dashboards', '/project/1/dashboard/42')
        expect(logic.values.interactedCards.dashboards).toBe(true)
    })
})
