import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HomeTabTemplateMatch, buildHomeTabAiPrompt, homeTabLogic, resolveHomeTabTemplateMatch } from './homeTabLogic'

describe('homeTabLogic', () => {
    describe('resolveHomeTabTemplateMatch', () => {
        it.each<[string, Parameters<typeof resolveHomeTabTemplateMatch>[0], HomeTabTemplateMatch]>([
            [
                'a named template ignores free text entirely',
                { templateKey: 'SaaS product', freeText: 'a taco delivery app', searchResultTemplateNames: [] },
                { action: 'use_template', templateKey: 'SaaS product' },
            ],
            [
                'no free text falls back to the generic template',
                { templateKey: 'Product analytics', freeText: undefined, searchResultTemplateNames: [] },
                { action: 'use_template', templateKey: 'Product analytics' },
            ],
            [
                'free text with a specific search hit uses that template',
                {
                    templateKey: 'Product analytics',
                    freeText: 'we sell shoes online',
                    searchResultTemplateNames: ['Product analytics', 'E-commerce'],
                },
                { action: 'use_template', templateKey: 'E-commerce' },
            ],
            [
                'free text where search only turns up the generic template hands off to AI',
                {
                    templateKey: 'Product analytics',
                    freeText: 'a satellite telemetry dashboard for farmers',
                    searchResultTemplateNames: ['Product analytics'],
                },
                { action: 'ai_handoff' },
            ],
            [
                'free text with no search results hands off to AI',
                {
                    templateKey: 'Product analytics',
                    freeText: 'a satellite telemetry dashboard',
                    searchResultTemplateNames: [],
                },
                { action: 'ai_handoff' },
            ],
        ])('%s', (_name, input, expected) => {
            expect(resolveHomeTabTemplateMatch(input)).toEqual(expected)
        })
    })

    describe('buildHomeTabAiPrompt', () => {
        it('includes the free text so PostHog AI knows what to build', () => {
            expect(buildHomeTabAiPrompt('a marketplace for freelance designers')).toContain(
                'a marketplace for freelance designers'
            )
        })
    })

    describe('createHomeTabDashboard', () => {
        it('creates from the exact template and never calls template search for a named button', async () => {
            let searchCalled = false
            let createUsedTemplate: string | undefined
            useMocks({
                get: {
                    '/api/projects/:team_id/dashboard_templates/': () => {
                        searchCalled = true
                        return [200, { count: 0, next: null, previous: null, results: [] }]
                    },
                },
                post: {
                    '/api/projects/:team_id/dashboards/': async ({ request }) => {
                        const body = (await request.json()) as { use_template?: string }
                        createUsedTemplate = body.use_template
                        return [200, { id: 123 }]
                    },
                },
            })
            initKeaTests()
            const logic = homeTabLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.createHomeTabDashboard({ templateKey: 'SaaS product', label: 'SaaS product' })
            }).toDispatchActions(['createHomeTabDashboardSuccess'])

            expect(searchCalled).toBe(false)
            expect(createUsedTemplate).toBe('SaaS product')
            expect(logic.values.homeTabDashboard).toEqual(expect.objectContaining({ id: 123 }))

            logic.unmount()
        })

        it('hands off to PostHog AI and does not create a dashboard when nothing matches', async () => {
            let dashboardCreateCalled = false
            useMocks({
                get: {
                    '/api/projects/:team_id/dashboard_templates/': () => [
                        200,
                        { count: 0, next: null, previous: null, results: [] },
                    ],
                },
                post: {
                    '/api/projects/:team_id/dashboards/': () => {
                        dashboardCreateCalled = true
                        return [200, { id: 123 }]
                    },
                },
            })
            initKeaTests()
            const logic = homeTabLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.createHomeTabDashboard({
                    templateKey: '__free_text__',
                    label: 'a satellite telemetry dashboard',
                    freeText: 'a satellite telemetry dashboard for farmers',
                })
            }).toDispatchActions(['createHomeTabDashboardSuccess'])

            expect(dashboardCreateCalled).toBe(false)
            expect(logic.values.homeTabDashboard).toBeNull()
            expect(router.values.location.pathname).toMatch(/\/ai$/)
            const askParam = new URLSearchParams(router.values.location.search).get('ask')
            expect(askParam).toContain('a satellite telemetry dashboard for farmers')

            logic.unmount()
        })
    })
})
