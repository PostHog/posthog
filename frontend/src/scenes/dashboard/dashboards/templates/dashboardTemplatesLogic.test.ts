import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { dashboardTemplatesLogic } from './dashboardTemplatesLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

describe('dashboardTemplatesLogic', () => {
    let logic: ReturnType<typeof dashboardTemplatesLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                'api/projects/:team_id/dashboard_templates/repository/': [
                    {
                        name: 'Product analytics',
                        url: null,
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
                'api/projects/:team_id/dashboard_templates/': [],
            },
        })

        initKeaTests()

        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DASHBOARD_TEMPLATES], {
            [FEATURE_FLAGS.DASHBOARD_TEMPLATES]: true,
        })

        logic = dashboardTemplatesLogic()
        logic.mount()
    })

    it('loads templates on mount', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadRepository', 'loadRepositorySuccess'])
            .toMatchValues({
                repository: {
                    'Website traffic': {
                        description: 'The website analytics dashboard that PostHog uses',
                        installed: false,
                        maintainer: 'official',
                        name: 'Website traffic',
                        url: 'https://raw.githubusercontent.com/PostHog/templates-repository/7916bed2463112a6354078065db1892eda51fd17/dashboards/posthog-website-traffic.json',
                        verified: true,
                    },
                    'Product analytics': {
                        description: 'The OG PostHog product analytics dashboard template',
                        installed: true,
                        maintainer: 'official',
                        name: 'Product analytics',
                        url: null,
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
