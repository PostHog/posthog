import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AccountAssignmentFilter } from './AccountAssignmentFilter'
import type { AssignmentStatus } from './accountAssignmentFilterTypes'

describe('AccountAssignmentFilter', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/members/': () => [200, { results: [] }],
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    function renderFilter({
        status = 'all',
        assignedToUserIds = [],
        onStatusChange = jest.fn(),
    }: {
        status?: AssignmentStatus
        assignedToUserIds?: number[]
        onStatusChange?: jest.Mock
    } = {}): void {
        render(
            <Provider>
                <AccountAssignmentFilter
                    status={status}
                    assignedToUserIds={assignedToUserIds}
                    onStatusChange={onStatusChange}
                    onAssignedToUserIdsChange={jest.fn()}
                />
            </Provider>
        )
    }

    it.each([
        ['all', [], 'All accounts'],
        ['assigned', [], 'Assigned to anyone'],
        ['assigned', [1], 'Assigned to 1 person'],
        ['assigned', [1, 2], 'Assigned to 2 people'],
        ['unassigned', [], 'Unassigned only'],
    ] as const)('labels %s with %s assignees', (status, assignedToUserIds, label) => {
        renderFilter({ status, assignedToUserIds: [...assignedToUserIds] })

        expect(screen.getByText(label)).toBeInTheDocument()
    })

    it('offers and selects each assignment status', () => {
        const onStatusChange = jest.fn()
        renderFilter({ onStatusChange })

        fireEvent.click(screen.getByText('All accounts'))

        for (const label of ['Unassigned only', 'Assigned to anyone', 'All assignment statuses']) {
            expect(screen.getByText(label)).toBeInTheDocument()
        }

        fireEvent.click(screen.getByText('Assigned to anyone'))
        expect(onStatusChange).toHaveBeenCalledWith('assigned')
    })
})
