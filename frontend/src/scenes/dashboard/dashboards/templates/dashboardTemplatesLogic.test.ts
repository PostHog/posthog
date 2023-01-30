import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { dashboardTemplatesLogic } from './dashboardTemplatesLogic'

describe('dashboardTemplatesLogic', () => {
    let logic: ReturnType<typeof dashboardTemplatesLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                'api/projects/@current/dashboard_templates/repository/': [
                    {
                        name: 'Product analytics',
                        url: 'https://raw.githubusercontent.com/PostHog/templates-repository/8e3cc02518644c9b6e458b2fc6eb4504e3957f07/dashboards/posthog-product-analytics.json',
                        description: 'The OG PostHog product analytics dashboard template',
                        verified: true,
                        maintainer: 'official',
                        installed: true,
                    },
                    {
                        name: 'Website traffic',
                        url: 'https://raw.githubusercontent.com/PostHog/templates-repository/7916bed2463112a6354078065db1892eda51fd17/dashboards/posthog-website-traffic.json',
                        description: 'The website analytics dashboard that PostHog uses',
                        verified: true,
                        maintainer: 'official',
                        installed: false,
                    },
                ],
            },
        })
        initKeaTests()
        logic = dashboardTemplatesLogic()
        logic.mount()
    })

    it('loads templates on mount', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadRepository', 'loadRepositorySuccess'])
            .toMatchValues({
                repository: {
                    'https://raw.githubusercontent.com/PostHog/templates-repository/7916bed2463112a6354078065db1892eda51fd17/dashboards/posthog-website-traffic.json':
                        {
                            description: 'The website analytics dashboard that PostHog uses',
                            installed: false,
                            maintainer: 'official',
                            name: 'Website traffic',
                            url: 'https://raw.githubusercontent.com/PostHog/templates-repository/7916bed2463112a6354078065db1892eda51fd17/dashboards/posthog-website-traffic.json',
                            verified: true,
                        },
                    'https://raw.githubusercontent.com/PostHog/templates-repository/8e3cc02518644c9b6e458b2fc6eb4504e3957f07/dashboards/posthog-product-analytics.json':
                        {
                            description: 'The OG PostHog product analytics dashboard template',
                            installed: true,
                            maintainer: 'official',
                            name: 'Product analytics',
                            url: 'https://raw.githubusercontent.com/PostHog/templates-repository/8e3cc02518644c9b6e458b2fc6eb4504e3957f07/dashboards/posthog-product-analytics.json',
                            verified: true,
                        },
                },
            })
    })
    it('only shows installed templates as available for use', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadRepository', 'loadRepositorySuccess'])
            .toMatchValues({
                templatesList: [
                    {
                        'data-attr': 'dashboard-select-Product-analytics',
                        label: 'Product analytics',
                        value: 'Product analytics',
                    },
                ],
            })
    })
})
