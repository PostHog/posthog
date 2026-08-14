import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { DashboardGroupApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'

import { initKeaTests } from '~/test/init'

import { DashboardSectionHeader } from './DashboardSectionHeader'

const group: DashboardGroupApi = {
    id: 'section-1',
    name: 'Acquisition',
    position: 1,
    member_tile_ids: [],
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    last_modified_at: '2026-01-01T00:00:00Z',
    last_modified_by: null,
}

describe('DashboardSectionHeader', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('deletes an empty section without a confirmation dialog', async () => {
        const onDelete = jest.fn()
        render(
            <DashboardSectionHeader
                group={group}
                collapsed={false}
                canEdit={true}
                tileCount={0}
                onToggle={jest.fn()}
                onRename={jest.fn()}
                onDelete={onDelete}
            />
        )

        await userEvent.click(document.querySelector('[data-attr="dashboard-section-menu"]')!)
        await userEvent.click(await screen.findByText('Delete'))

        expect(onDelete).toHaveBeenCalledWith('delete_tiles')
        expect(screen.queryByText('Delete section?')).not.toBeInTheDocument()
    })
})
