import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { LineageNode } from 'products/data_modeling/frontend/lineage/LineageNode'

describe('LineageNode', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([false, true])('shows refresh status only for materialized endpoints (%s)', (isMaterialized) => {
        render(
            <LineageNode
                data={{
                    node: {
                        id: 'published-model',
                        name: 'weekly_activity_v2',
                        type: 'endpoint',
                        endpoint: { name: 'weekly_activity', version: 2, is_materialized: isMaterialized },
                        upstream_count: 1,
                        downstream_count: 0,
                    },
                    variant: 'full',
                    direction: 'RIGHT',
                    state: {},
                    callbacks: {},
                    handles: [],
                }}
            />
        )

        expect(screen.getByText('weekly_activity v2')).not.toBeNull()
        expect(screen.queryByText('weekly_activity_v2')).toBeNull()
        expect(screen.queryByText('Never succeeded') !== null).toBe(isMaterialized)
        expect(screen.queryByText('Inline') !== null).toBe(!isMaterialized)
    })
})
