import { fireEvent, render } from '@testing-library/react'

import { DashboardPlacement, QueryBasedInsightModel } from '~/types'

import { InsightCard } from './InsightCard'

const makeInsight = (): QueryBasedInsightModel =>
    ({
        id: 1,
        short_id: 'shortid' as QueryBasedInsightModel['short_id'],
        name: 'Test insight',
        result: null,
        last_refresh: null,
        created_at: '2021-01-01T00:00:00Z',
        updated_at: '2021-01-01T00:00:00Z',
        derived_name: null,
        tags: [],
        effective_privilege_level: null,
        filters: null,
        query: { kind: 'HogQLQuery', query: 'SELECT 1' } as any,
        dashboards: [],
        dashboard_tiles: [],
        is_sample: false,
        deleted: false,
        is_cached: false,
        saved: true,
        order: 0,
        user_access_level: 0 as any,
        created_by: null,
        last_modified_at: '2021-01-01T00:00:00Z',
        last_modified_by: null,
        timezone: null,
    }) as unknown as QueryBasedInsightModel

describe('InsightCard', () => {
    it('calls onDragHandleMouseDown when mousing down on CardMeta', () => {
        const onDragHandleMouseDown = jest.fn()

        const { container } = render(
            <InsightCard
                insight={makeInsight()}
                placement={DashboardPlacement.Dashboard}
                onDragHandleMouseDown={onDragHandleMouseDown}
            />
        )

        const meta = container.querySelector('.CardMeta') as HTMLElement
        fireEvent.mouseDown(meta)

        expect(onDragHandleMouseDown).toHaveBeenCalledTimes(1)
    })
})
