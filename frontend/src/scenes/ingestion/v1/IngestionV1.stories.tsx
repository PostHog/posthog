import { Meta } from '@storybook/react'
import { mswDecorator } from '~/mocks/browser'

import { IngestionWizardV1 } from './IngestionWizard'

export default {
    title: 'Scenes-Other/Onboarding',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/ingestion_warnings': {
                    warnings: [
                        {
                            team_id: '1',
                            type: 'duplicate',
                            source: 'plugin-server',
                            details: {
                                message: 'Duplicate event',
                            },
                            timestamp: '2021-05-18T12:00:00.000Z',
                        },
                    ],
                },
            },
        }),
    ],
} as Meta

export const IngestionV1 = (): JSX.Element => <IngestionWizardV1 />
