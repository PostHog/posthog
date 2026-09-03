import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { FlatNav } from './FlatNav'

type Story = StoryObj<typeof FlatNav>

const meta: Meta<typeof FlatNav> = {
    title: 'Layout/Flat Nav',
    component: FlatNav,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.FLAT_NAV],
    },
    render: () => (
        <div className="h-screen w-fit">
            <FlatNav />
        </div>
    ),
}

export default meta

export const Default: Story = {}
