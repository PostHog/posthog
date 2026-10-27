// PROTOTYPE — scratch story to view the property usage variants. Use the bottom bar or `&variant=` / `&scenario=`.
import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const MOCK_PROPERTY_DEFINITION = {
    id: '0190a1b2-0000-0000-0000-000000000001',
    name: 'plan',
    description: 'The billing plan the account is on',
    tags: ['billing'],
    is_numerical: false,
    property_type: 'String',
    type: 1,
    verified: false,
    hidden: false,
    updated_at: '2026-04-15T10:00:00Z',
    updated_by: { id: 1, first_name: 'Demo', email: 'demo@posthog.com' },
}

const meta: Meta = {
    component: App,
    title: 'Prototypes/Property usage',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-04-30',
        pageUrl: urls.propertyDefinition(MOCK_PROPERTY_DEFINITION.id),
        testOptions: { skip: true },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project_id/property_definitions/:id/': MOCK_PROPERTY_DEFINITION,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const PropertyUsage: Story = {}
