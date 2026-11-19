import type { Meta, StoryObj } from '@storybook/react'
import { kea, path, useMountedLogic } from 'kea'
import { useState } from 'react'

import { ProductKey } from '~/queries/schema/schema-general'

import { productSetupStatusLogic } from './productSetupStatusLogic'
import { SetupListeningIndicator } from './SetupListeningIndicator'
import type { ProductSetupStatus } from './types'

const storyDetectionLogic = kea([path(['lib', 'components', 'ProductEmptyState', 'storyDetectionLogic'])])

const meta: Meta<typeof SetupListeningIndicator> = {
    title: 'Components/Product Empty State/Setup Listening Indicator',
    component: SetupListeningIndicator,
    // The listening state keeps a spinner up by design.
    parameters: { layout: 'padded', testOptions: { waitForLoadersToDisappear: false } },
}
export default meta

type Story = StoryObj<typeof SetupListeningIndicator>

function renderWithStatus(status: ProductSetupStatus): Story['render'] {
    return function Render() {
        const logic = useMountedLogic(productSetupStatusLogic({ productKey: ProductKey.TRACING }))
        useState(() => logic.actions.setDetectedStatus(status))
        return (
            <div className="max-w-[36rem]">
                <SetupListeningIndicator
                    productKey={ProductKey.TRACING}
                    statusLogic={storyDetectionLogic}
                    dataName="span"
                    destination={{ label: 'Go to Tracing', url: '/tracing' }}
                />
            </div>
        )
    }
}

export const Listening: Story = { render: renderWithStatus('needs-setup') }

export const DataReceived: Story = { render: renderWithStatus('has-data') }

export const DetectionUnavailable: Story = { render: renderWithStatus('unknown') }
