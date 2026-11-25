import { cleanup, fireEvent, render } from '@testing-library/react'

import type { SyncFrequencyBoundsApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { QuillSyncFrequencySelect } from './QuillSyncFrequencySelect'
import { CadencePin } from './SyncFrequencySelect'

const PIN: CadencePin = { pinned: true, pending: false, delayed: [], blockedBy: {}, delaysBy: {}, unpinnedBy: {} }

function boundsWithPlanFloorAt6Hours(): SyncFrequencyBoundsApi {
    return {
        frequency_mode: 'tiered',
        options: (['1hour', '6hour', '24hour'] as const).map((cadence) => ({
            cadence,
            allowed: cadence !== '1hour',
            blocked_by: cadence === '1hour' ? 'plan' : null,
            blocker: null,
            speeds_up: [],
            speeds_up_withheld: false,
        })),
        floor: null,
        plan_floor: { label: '6 hours', blocker: null },
        ceiling: null,
        best_effort_sources: [],
        best_effort_sources_withheld: false,
    } as unknown as SyncFrequencyBoundsApi
}

describe('QuillSyncFrequencySelect', () => {
    afterEach(cleanup)

    it('lets a pin saved below the plan floor be unpinned', () => {
        const onUnpin = jest.fn()
        const { container } = render(
            <QuillSyncFrequencySelect
                bounds={boundsWithPlanFloorAt6Hours()}
                value="1hour"
                onChange={jest.fn()}
                pin={PIN}
                onUnpin={onUnpin}
            />
        )

        const pinned = container.querySelector('[data-attr="sync-frequency-unpin"]')
        expect(pinned).not.toBeNull()
        fireEvent.click(pinned!)
        expect(onUnpin).toHaveBeenCalledTimes(1)
    })
})
