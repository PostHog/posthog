import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { AccountDotMatrixTile } from './AccountDotMatrixTile'

const meta: Meta<typeof AccountDotMatrixTile> = {
    title: 'Customer Analytics/Account views/Dot matrix',
    component: AccountDotMatrixTile,
    args: { instanceId: 'dot-matrix-example' },
    parameters: {
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS_DOT_MATRIX],
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="account-dot-matrix-tile"]' },
    },
    decorators: [
        (Story) => (
            <div className="w-128">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof AccountDotMatrixTile>

export const PeopleActivity: Story = {}

export const SavedCiConfig: Story = {
    args: { initialConfig: { dataset: 'ci', mode: 'count', selectedSeries: [] } },
}
