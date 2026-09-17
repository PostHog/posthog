import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { openModelNode } from './modelNodeNavigation'

describe('openModelNode', () => {
    beforeEach(() => initKeaTests())

    it('opens an endpoint version from a graph', () => {
        openModelNode({
            id: 'node',
            type: 'endpoint',
            endpoint: { name: 'weekly_activity', version: 2, is_materialized: false },
        })
        expect(router.values.location.pathname).toBe(`/project/997${urls.endpoint('weekly_activity')}`)
        expect(router.values.searchParams).toMatchObject({ version: 2, tab: 'lineage' })
    })

    it('sends orphaned endpoint nodes to the list with an explanation', () => {
        const toast = jest.spyOn(lemonToast, 'info')
        openModelNode({ id: 'orphan', type: 'endpoint' })
        expect(router.values.location.pathname).toBe(`/project/997${urls.endpoints()}`)
        expect(toast).toHaveBeenCalledWith(
            'This model is no longer linked to an endpoint. Choose an endpoint from the list.'
        )
        toast.mockRestore()
    })

    it('keeps regular models on their model scene', () => {
        openModelNode({ id: 'view', type: 'view' }, 'lineage')
        expect(router.values.location.pathname).toBe(`/project/997${urls.nodeDetail('view', 'lineage')}`)
    })
})
