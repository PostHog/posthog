import '@testing-library/jest-dom'

import { DndContext } from '@dnd-kit/core'
import { render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { eventFilterLogic, FilterNode, normalizeRootToGroup } from './eventFilterLogic'
import { NodeEditor } from './EventFilterTreeEditor'
import { NodeIdMap } from './NodeIdMap'
import { cond } from './testHelpers'

describe('EventFilterTreeEditor delete affordance', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/event_filter/': () => [200, null] } })
        initKeaTests()
        eventFilterLogic.mount()
    })

    function renderRoot(node: FilterNode): void {
        const nodeIds = new NodeIdMap()
        nodeIds.buildIndex(node)
        render(
            <DndContext>
                <NodeEditor node={node} path={[]} depth={0} nodeIds={nodeIds} />
            </DndContext>
        )
    }

    it('shows no Remove button for a bare condition at the root — reproduces the original bug', () => {
        // The backend used to collapse a one-condition filter down to a bare condition,
        // which renders with no delete handler and therefore no way to remove it.
        renderRoot(cond('event_name', 'exact', 'pageview'))
        expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
    })

    it('shows a Remove button once the root is normalized to a group', () => {
        renderRoot(normalizeRootToGroup(cond('event_name', 'exact', 'pageview')))
        expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
    })
})
