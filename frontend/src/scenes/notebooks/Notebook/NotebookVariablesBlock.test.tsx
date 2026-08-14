import { cleanup, fireEvent, render, within } from '@testing-library/react'

import { NotebookVariable, getNotebookVariableErrors } from './notebookVariables'
import { NotebookVariablesDeclarationPanel, NotebookVariablesValuePanel } from './NotebookVariablesBlock'

describe('NotebookVariablesBlock', () => {
    const country: NotebookVariable = { name: 'country', type: 'string', value: 'US' }
    const days: NotebookVariable = { name: 'lookback_days', type: 'number', value: 30 }

    // This suite runs without RTL auto-cleanup, so an earlier test's DOM would otherwise stay
    // mounted and its label/control ids would resolve ahead of the ones under test.
    afterEach(cleanup)

    // Scoped to each render's own container for the same reason.
    const renderValues = (variables: NotebookVariable[]): { panel: ReturnType<typeof within>; onChange: jest.Mock } => {
        const onChange = jest.fn()
        const { container } = render(
            <NotebookVariablesValuePanel
                variables={variables}
                errors={getNotebookVariableErrors(variables)}
                disabled={false}
                onChange={onChange}
            />
        )
        return { panel: within(container), onChange }
    }

    const renderDeclarations = (
        variables: NotebookVariable[]
    ): { panel: ReturnType<typeof within>; onChange: jest.Mock } => {
        const onChange = jest.fn()
        const { container } = render(
            <NotebookVariablesDeclarationPanel
                variables={variables}
                errors={getNotebookVariableErrors(variables)}
                onChange={onChange}
            />
        )
        return { panel: within(container), onChange }
    }

    it('labels each value control with its variable name', () => {
        const { panel } = renderValues([country, days])

        expect(panel.getByLabelText('country')).toHaveProperty('value', 'US')
        expect(panel.getByLabelText('lookback_days')).toHaveProperty('value', '30')
    })

    it('editing a value reports the whole updated set', () => {
        // The block persists all of its declarations at once, so a single edit must not drop
        // the variables it did not touch.
        const { panel, onChange } = renderValues([country, days])

        fireEvent.change(panel.getByLabelText('country'), { target: { value: 'DE' } })

        expect(onChange).toHaveBeenCalledWith([{ ...country, value: 'DE' }, days])
    })

    it('a boolean renders a checkbox rather than a text field', () => {
        const { panel } = renderValues([{ name: 'include_bots', type: 'boolean', value: false }])

        expect(panel.getByLabelText('include_bots')).toHaveProperty('checked', false)
    })

    it('surfaces a duplicate name as an error on the second declaration', () => {
        // Uniqueness is the rule the whole feature rests on — a duplicate that only failed at
        // dispatch would leave the user guessing which value bound.
        const { panel } = renderValues([country, { ...country, value: 'DE' }])

        expect(panel.getByText(/already declared/)).toBeTruthy()
    })

    it('tells a reader with no variables how to use one', () => {
        const { panel } = renderValues([])

        expect(panel.getByText(/No variables yet/)).toBeTruthy()
    })

    it('adding a variable appends an empty row', () => {
        const { panel, onChange } = renderDeclarations([country])

        fireEvent.click(panel.getByText('Add variable'))

        expect(onChange).toHaveBeenCalledWith([country, { name: '', type: 'string', value: '' }])
    })

    it('removing a variable drops only that one', () => {
        const { panel, onChange } = renderDeclarations([country, days])

        fireEvent.click(panel.getByLabelText('Remove country', { selector: 'button' }))

        expect(onChange).toHaveBeenCalledWith([days])
    })
})
