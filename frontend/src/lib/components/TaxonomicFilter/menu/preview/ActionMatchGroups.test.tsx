import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { actionsModel } from '~/models/actionsModel'
import { initKeaTests } from '~/test/init'

import { ActionMatchGroups } from './ActionMatchGroups'

jest.mock('lib/api', () => {
    const emptyPaginated = (): Promise<{ results: any[]; count: number; next: null }> =>
        Promise.resolve({ results: [], count: 0, next: null })
    return {
        __esModule: true,
        default: {
            get: jest.fn().mockImplementation(emptyPaginated),
            actions: { list: jest.fn() },
        },
    }
})

const apiActionsList = jest.requireMock('lib/api').default.actions.list as jest.Mock

const TEST_ACTION = {
    id: 282580,
    name: "Vasco's Test action",
    steps: [
        {
            event: '$pageview',
            properties: [{ key: '$os_version', value: '14.4.1', operator: 'semver_gte' }],
        },
    ],
}

function renderItem(item: any): ReturnType<typeof render> {
    return render(
        <Provider>
            <ActionMatchGroups item={item} />
        </Provider>
    )
}

describe('ActionMatchGroups', () => {
    beforeEach(async () => {
        apiActionsList.mockResolvedValue({ results: [TEST_ACTION], count: 1, next: null })
        initKeaTests()
        actionsModel.mount()
        await waitFor(() => {
            if (actionsModel.values.actions.length !== 1) {
                throw new Error('actions not loaded yet')
            }
        })
    })

    afterEach(() => cleanup())

    it('renders match groups directly when the entry item already carries steps', () => {
        renderItem(TEST_ACTION)
        expect(screen.getByText('$os_version')).toBeInTheDocument()
        expect(screen.getByText('greater than or equal (semver)')).toBeInTheDocument()
    })

    it('hydrates a step-less {id,name} shim from actionsModel so match groups still render', () => {
        // The committed selection on the "All" surface is a lightweight shim with no `steps`;
        // it must still show the action's match groups (the bug was a blank preview there).
        renderItem({ id: 282580, name: "Vasco's Test action" })
        expect(screen.getByText('$os_version')).toBeInTheDocument()
        expect(screen.getByText('greater than or equal (semver)')).toBeInTheDocument()
    })

    it('renders nothing for a step-less item with no matching action', () => {
        const { container } = renderItem({ id: 999999, name: 'unknown' })
        expect(container).toBeEmptyDOMElement()
    })
})
