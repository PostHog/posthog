import React from 'react'
import { Meta } from '@storybook/react'
import { mswDecorator } from '~/mocks/browser'
import { Dashboard } from './Dashboard'

export default {
    title: 'Scenes/Dashboard',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/1/dashboards/': require('./__mocks__/dashboards.json'),
                '/api/projects/1/dashboards/1/': require('./__mocks__/dashboard1.json'),
                '/api/projects/1/dashboards/1/collaborators/': [],
            },
        }),
    ],
    parameters: { options: { showPanel: false }, viewMode: 'canvas' },
} as Meta

export const Default = (): JSX.Element => {
    return <Dashboard id={'1'} />
}
