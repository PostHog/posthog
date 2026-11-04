import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { MacrosSection } from '../../scenes/settings/MacrosSection'
import { MacroPicker } from './MacroPicker'

const macros = {
    count: 1,
    next: null,
    previous: null,
    results: [
        {
            id: '11111111-1111-1111-1111-111111111111',
            name: 'Cancellation',
            shortcut: 'cancel',
            body: 'Hi {{customer.first_name}},\n\nYour subscription is cancelled.',
            usage_count: 4,
            last_used_at: '2026-01-15T12:00:00Z',
            created_at: '2026-01-01T12:00:00Z',
            updated_at: null,
            created_by: {
                id: 1,
                uuid: 'user-1',
                distinct_id: 'user-1',
                first_name: 'Nik',
                email: 'nik@example.com',
            },
        },
    ],
}

const meta: Meta = {
    title: 'Scenes-App/Support/Macros',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/conversations/macros/': macros,
            },
        }),
    ],
    parameters: {
        layout: 'padded',
        mockDate: '2026-01-15',
        featureFlags: [FEATURE_FLAGS.PRODUCT_SUPPORT_MACROS],
    },
}
export default meta

type Story = StoryObj

export const Picker: Story = {
    parameters: { testOptions: { waitForSelector: 'text=Macros' } },
    render: () => (
        <div className="w-[520px]">
            <MacroPicker onInsert={() => undefined} />
        </div>
    ),
}

export const Settings: Story = {
    parameters: { testOptions: { waitForSelector: 'text=Cancellation' } },
    render: () => (
        <div className="w-[520px]">
            <MacrosSection />
        </div>
    ),
}
