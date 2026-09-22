import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { FlatNavBrowse } from './FlatNavBrowse'

type Story = StoryObj<typeof FlatNavBrowse>

const meta: Meta<typeof FlatNavBrowse> = {
    title: 'Layout/Flat Nav Browse',
    component: FlatNavBrowse,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: { [FEATURE_FLAGS.FLAT_NAV]: 'test' },
    },
    render: () => (
        <div className="h-screen w-[var(--project-navbar-width)] flex flex-col">
            <FlatNavBrowse />
        </div>
    ),
}

export default meta

export const Default: Story = {}
