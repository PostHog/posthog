import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'
import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'

import { Schemas, SchemasProps } from './Schemas'

type Story = StoryObj<SchemasProps>
const meta: Meta<SchemasProps> = {
    title: 'Scenes-App/Data Warehouse/Settings/Schemas',
    component: Schemas,
    args: {
        id: '123',
    },
    parameters: {
        mockDate: '2023-02-01',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.REVENUE_ANALYTICS],
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
    },
    render: (props) => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/:id': () => {
                    return [200, externalDataSourceResponseMock]
                },
            },
        })

        return <Schemas {...props} />
    },
}

export default meta

export const Default: Story = {
    args: {},
}
