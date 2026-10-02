import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { viewsLogic } from './viewsLogic'
import { ViewItem } from './viewsUtils'

jest.mock('posthog-js')

describe('viewsLogic', () => {
    it('shows views in batches and resets the batch when the type changes', () => {
        initKeaTests()
        const logic = viewsLogic()
        logic.mount()

        const items: ViewItem[] = Array.from({ length: 120 }, (_, index) => ({
            type: index < 60 ? 'dashboard' : 'canvas',
            id: String(index),
            name: `View ${index}`,
            href: `/views/${index}`,
            timestamp: null,
            timestampLabel: 'Created',
            spaceId: null,
            spaceName: null,
            createdByUuid: null,
            firstBuildTaskId: null,
        }))
        logic.actions.receiveViews({ items, failedTypes: [] })
        expect(logic.values.visibleViews).toHaveLength(50)
        expect(logic.values.hasMoreViews).toBe(true)

        logic.actions.showMoreViews()
        expect(logic.values.visibleViews).toHaveLength(100)

        logic.actions.setTypeFilter('dashboard')
        expect(logic.values.visibleViews).toHaveLength(50)
        expect(logic.values.hasMoreViews).toBe(true)

        logic.actions.showMoreViews()
        expect(logic.values.visibleViews).toHaveLength(60)
        expect(logic.values.hasMoreViews).toBe(false)

        logic.unmount()
        expect(posthog.capture).toHaveBeenCalledWith('views list filtered', { type: 'dashboard' })
    })
})
