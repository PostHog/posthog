import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { performQuery } from '~/queries/query'
import { HogQLQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { ListVariable } from '../../types'
import { ListVariableSelect } from './VariableFields'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

const schoolsVariable: ListVariable = {
    id: 'schools-variable',
    name: 'School',
    code_name: 'school',
    type: 'List',
    values: [],
    default_value: '',
    values_query: 'SELECT name FROM schools ORDER BY name',
}

const ALL_SCHOOLS = Array.from({ length: 150 }, (_, index) => [`school-${String(index).padStart(3, '0')}`])

describe('ListVariableSelect', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(performQuery).mockImplementation(async (node) => {
            // HogQL gives a query without its own LIMIT 100 rows, so the mock has to as well.
            const rowLimit = /LIMIT (\d+)\s*$/.exec((node as HogQLQuery).query)?.[1]
            return { results: ALL_SCHOOLS.slice(0, rowLimit ? Number(rowLimit) : 100) }
        })
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    // The dropdown filters what it loaded, so a value the options query returns past the first page
    // used to answer a search for it with "No options matching".
    it('finds a value the options query returns past its first page', async () => {
        render(
            <Provider>
                <ListVariableSelect variable={schoolsVariable} onChange={() => {}} />
            </Provider>
        )

        const input = await screen.findByPlaceholderText('Select a value')
        await userEvent.click(input)
        await waitFor(() => expect(screen.getByText('school-000')).toBeInTheDocument())

        await userEvent.type(input, 'school-149')

        expect(await screen.findByText('school-149')).toBeInTheDocument()
        expect(screen.queryByText('No options matching')).not.toBeInTheDocument()
    })
})
