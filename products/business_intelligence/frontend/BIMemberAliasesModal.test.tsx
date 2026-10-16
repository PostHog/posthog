import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import * as queryRunner from '~/queries/query'
import { BIField } from '~/queries/schema/schema-business-intelligence'
import { initKeaTests } from '~/test/init'

import { biMemberAliasesLogic } from './biMemberAliasesLogic'
import { BIMemberAliasesModal } from './BIMemberAliasesModal'

describe('member alias editor', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('bounds rendered inputs and keeps edits stable across pages and saved-alias search', async () => {
        jest.spyOn(queryRunner, 'performQuery').mockResolvedValue({ results: [] } as never)
        const props = { tabId: 'alias-pagination-test' }
        const logic = biMemberAliasesLogic(props)
        logic.mount()
        const field: BIField = {
            id: 'region',
            name: 'Region',
            expression: 'region',
            type: 'string',
            source: { table: 'example_orders' },
        }
        logic.actions.edit(
            field,
            Array.from({ length: 101 }, (_, i) => ({ value: `value-${i}`, label: `Label ${i}` }))
        )
        render(<BIMemberAliasesModal {...props} />)
        await waitFor(() => expect(screen.getAllByLabelText(/^Alias for /)).toHaveLength(50))
        const first = screen.getByLabelText('Alias for value-0')
        fireEvent.change(first, { target: { value: 'Updated first' } })
        expect(screen.getByLabelText('Alias for value-0')).toHaveValue('Updated first')
        fireEvent.click(screen.getByLabelText('Next page'))
        expect(screen.queryByLabelText('Alias for value-0')).not.toBeInTheDocument()
        expect(screen.getAllByLabelText(/^Alias for /)).toHaveLength(50)
        fireEvent.click(screen.getByLabelText('Previous page'))
        expect(screen.getByLabelText('Alias for value-0')).toHaveValue('Updated first')
        fireEvent.change(screen.getByLabelText('Search member values and aliases'), { target: { value: 'Label 100' } })
        expect(await screen.findByLabelText('Alias for value-100')).toHaveValue('Label 100')
        expect(screen.getAllByLabelText(/^Alias for /)).toHaveLength(1)
        const matchingInput = screen.getByLabelText('Alias for value-100')
        matchingInput.focus()
        fireEvent.change(matchingInput, { target: { value: '' } })
        expect(screen.getByLabelText('Alias for value-100')).toBe(matchingInput)
        expect(matchingInput).toHaveFocus()
        fireEvent.change(matchingInput, { target: { value: 'Replacement label' } })
        expect(matchingInput).toHaveValue('Replacement label')
        expect(logic.values.draft).toHaveLength(101)
        expect(logic.values.draft[0]).toEqual({ value: 'value-0', label: 'Updated first' })
        logic.unmount()
    })
})
