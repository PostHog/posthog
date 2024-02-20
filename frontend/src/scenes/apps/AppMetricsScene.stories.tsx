import { Meta, Story } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'

import { AppMetricsResponse } from './appMetricsSceneLogic'

const meta: Meta = {
    title: 'Scenes-App/Apps/App Metrics',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/app_metrics/:plugin_config_id/': {
                    metrics: {
                        dates: [
                            '2023-01-10',
                            '2023-01-11',
                            '2023-01-12',
                            '2023-01-13',
                            '2023-01-14',
                            '2023-01-15',
                            '2023-01-16',
                            '2023-01-17',
                            '2023-01-18',
                            '2023-01-19',
                            '2023-01-20',
                            '2023-01-21',
                            '2023-01-22',
                            '2023-01-23',
                            '2023-01-24',
                            '2023-01-25',
                            '2023-01-26',
                            '2023-01-27',
                            '2023-01-28',
                            '2023-01-29',
                            '2023-01-30',
                            '2023-01-31',
                            '2023-02-01',
                            '2023-02-02',
                            '2023-02-03',
                            '2023-02-04',
                            '2023-02-05',
                            '2023-02-06',
                            '2023-02-07',
                            '2023-02-08',
                            '2023-02-09',
                            '2023-02-10',
                        ],
                        successes: [
                            200284, 825910, 910238, 695212, 347366, 509484, 755095, 896207, 833688, 877957, 687831,
                            328978, 367202, 778454, 818080, 786804, 799241, 700601, 359021, 449898, 896344, 883930,
                            782438, 847738, 837096, 380913, 461850, 2197110, 2249144, 784267, 682512, 112651,
                        ],
                        failures: [
                            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                            0,
                        ],
                        totals: {
                            successes: 24043544,
                            failures: 0,
                        },
                    },
                    errors: [],
                } as AppMetricsResponse,
            },
        }),
    ],
}
export default meta
export const AppMetrics: Story = () => {
    useAvailableFeatures([AvailableFeature.APP_METRICS])
    useEffect(() => {
        router.actions.push(urls.appMetrics(1))
    })
    return <App />
}
