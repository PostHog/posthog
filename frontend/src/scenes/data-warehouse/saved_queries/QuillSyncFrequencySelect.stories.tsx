import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { DataModelingSyncInterval } from '~/types'

import type { SyncFrequencyBoundsApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { QuillSyncFrequencySelect } from './QuillSyncFrequencySelect'
import { CadencePin, SyncFrequencySelectProps } from './SyncFrequencySelect'

const CADENCES: DataModelingSyncInterval[] = ['15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day']
const CONSUMER = { id: 'view-2', name: 'revenue_daily' }

function boundsWithCeiling(ceiling: DataModelingSyncInterval): SyncFrequencyBoundsApi {
    const ceilingIndex = CADENCES.indexOf(ceiling)
    return {
        frequency_mode: 'tiered',
        options: CADENCES.map((cadence, index) => ({
            cadence,
            allowed: index <= ceilingIndex,
            blocked_by: index <= ceilingIndex ? null : 'consumer',
            blocker: index <= ceilingIndex ? null : CONSUMER,
            speeds_up: [],
            speeds_up_withheld: false,
        })),
        floor: null,
        plan_floor: null,
        ceiling: { label: '6 hours', blocker: CONSUMER },
        best_effort_sources: [],
        best_effort_sources_withheld: false,
    } as SyncFrequencyBoundsApi
}

function pinnedTo(pending: boolean): CadencePin {
    return {
        pinned: true,
        pending,
        delayed: [CONSUMER],
        blockedBy: {},
        delaysBy: { '24hour': [CONSUMER], '7day': [CONSUMER], '30day': [CONSUMER] },
        unpinnedBy: { '24hour': '6hour', '7day': '6hour', '30day': '6hour' },
    }
}

function SyncFrequencyStory(props: SyncFrequencySelectProps): JSX.Element {
    return (
        <div data-quill className="w-160 p-4">
            <QuillSyncFrequencySelect {...props} />
        </div>
    )
}

const meta: Meta<typeof SyncFrequencyStory> = {
    title: 'Scenes-App/Data Warehouse/Quill sync frequency select',
    component: SyncFrequencyStory,
    args: { onChange: () => {}, onUnpin: () => {} },
    parameters: {
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof SyncFrequencyStory>

export const Unbounded: Story = { args: { value: '24hour' } }

export const InheritedFromDownstreamView: Story = {
    args: { value: '24hour', bounds: boundsWithCeiling('6hour') },
}

export const Pinned: Story = {
    args: { value: '24hour', bounds: boundsWithCeiling('6hour'), pin: pinnedTo(false) },
}

export const PinPendingSave: Story = {
    args: { value: '24hour', bounds: boundsWithCeiling('6hour'), pin: pinnedTo(true) },
}
