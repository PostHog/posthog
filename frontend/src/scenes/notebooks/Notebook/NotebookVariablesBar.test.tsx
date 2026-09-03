import { cleanup, fireEvent, render, within } from '@testing-library/react'

import { MAX_NOTEBOOK_VARIABLES, NotebookVariable, getNotebookVariableErrors } from './notebookVariables'
import { NotebookVariablesPanel } from './NotebookVariablesBar'

describe('NotebookVariablesPanel', () => {
    const country: NotebookVariable = { name: 'country', type: 'string', value: 'US' }
    const days: NotebookVariable = { name: 'lookback_days', type: 'number', value: 30 }

    // This suite runs without RTL auto-cleanup, so an earlier test's DOM would otherwise stay
    // mounted and its label and control ids would resolve ahead of the ones under test.
    afterEach(cleanup)

    const renderPanel = (
        variables: NotebookVariable[],
        disabled = false
    ): { panel: ReturnType<typeof within>; onChange: jest.Mock } => {
        const onChange = jest.fn()
        const { container } = render(
            <NotebookVariablesPanel
                variables={variables}
                errors={getNotebookVariableErrors(variables)}
                disabled={disabled}
                onChange={onChange}
            />
        )
        return { panel: within(container), onChange }
    }

    it('renders one row per variable, with name, type and value together', () => {
        const { panel } = renderPanel([country, days])

        expect(panel.getByLabelText('Name of variable 1')).toHaveProperty('value', 'country')
        expect(panel.getByLabelText('Name of variable 2')).toHaveProperty('value', 'lookback_days')
        expect(panel.getByLabelText('Value of country')).toHaveProperty('value', 'US')
        expect(panel.getByLabelText('Value of lookback_days')).toHaveProperty('value', '30')
    })

    it('editing a value reports the whole updated set', () => {
        // The bar persists all of its declarations at once, so a single edit must not drop the
        // variables it did not touch.
        const { panel, onChange } = renderPanel([country, days])

        fireEvent.change(panel.getByLabelText('Value of country'), { target: { value: 'DE' } })

        expect(onChange).toHaveBeenCalledWith([{ ...country, value: 'DE' }, days])
    })

    it('a boolean renders a checkbox rather than a text field', () => {
        const { panel } = renderPanel([{ name: 'include_bots', type: 'boolean', value: false }])

        expect(panel.getByLabelText('Value of include_bots')).toHaveProperty('checked', false)
    })

    it('surfaces a duplicate name as an error on the second row', () => {
        // Uniqueness is the rule the whole feature rests on — a duplicate that only failed at
        // dispatch would leave the user guessing which value bound.
        const { panel } = renderPanel([country, { ...country, value: 'DE' }])

        expect(panel.getByText(/already declared/)).toBeTruthy()
    })

    it('tells a reader with no variables how to use one', () => {
        const { panel } = renderPanel([])

        expect(panel.getByText(/No variables yet/)).toBeTruthy()
    })

    it('adding a variable appends an empty row', () => {
        const { panel, onChange } = renderPanel([country])

        fireEvent.click(panel.getByText('Add variable'))

        expect(onChange).toHaveBeenCalledWith([country, { name: '', type: 'string', value: '' }])
    })

    it('removing a variable drops only that one', () => {
        const { panel, onChange } = renderPanel([country, days])

        fireEvent.click(panel.getByLabelText('Remove country', { selector: 'button' }))

        expect(onChange).toHaveBeenCalledWith([days])
    })

    it('stops offering to add past the limit', () => {
        // The API rejects an eleventh variable, so the bar must not let someone type one and
        // then lose the save.
        const many = Array.from({ length: MAX_NOTEBOOK_VARIABLES }, (_, index) => ({
            name: `v${index}`,
            type: 'string' as const,
            value: '',
        }))
        const { panel } = renderPanel(many)

        expect(panel.getByText('Add variable').closest('button')?.getAttribute('aria-disabled')).toEqual('true')
    })

    it('a read-only notebook cannot change a value', () => {
        const { panel } = renderPanel([country], true)

        expect(panel.getByLabelText('Value of country')).toHaveProperty('disabled', true)
    })
})
