import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { initKeaTests } from '~/test/init'

import { ActionMatchGroups } from './ActionMatchGroups'

const TEST_ACTION = {
    id: 282580,
    name: 'Test action',
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
        useMocks({ get: { '/api/projects/:team_id/actions/': { results: [TEST_ACTION], count: 1 } } })
        initKeaTests()
        actionsModel.mount()
        await waitFor(() => {
            if (actionsModel.values.actions.length !== 1) {
                throw new Error('actions not loaded yet')
            }
        })
    })

    afterEach(() => cleanup())

    // Both an item that already carries `steps` and a lightweight `{ id, name }` shim (the
    // committed selection on the "All" surface) must render the match groups — the bug was
    // that the shim, lacking `steps`, produced a blank preview.
    it.each([
        ['an item that already carries steps', TEST_ACTION],
        ['a step-less {id,name} shim hydrated from actionsModel', { id: TEST_ACTION.id, name: TEST_ACTION.name }],
    ])('renders match groups for %s', (_label, item) => {
        renderItem(item)
        expect(screen.getByText('$os_version')).toBeInTheDocument()
        expect(screen.getByText('greater than or equal (semver)')).toBeInTheDocument()
    })

    it('renders nothing for a step-less item with no matching action', () => {
        const { container } = renderItem({ id: 999999, name: 'unknown' })
        expect(container).toBeEmptyDOMElement()
    })
})
