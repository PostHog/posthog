import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { ListVariable } from '../../types'
import { VariableComponent } from './Variables'

describe('VariableComponent', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders a static single-select list variable on a dashboard as a dropdown, not an editable input', () => {
        const variable: ListVariable = {
            id: 'var-1',
            name: 'Country',
            code_name: 'country',
            type: 'List',
            values: ['United States', 'Germany', 'Japan'],
            value: 'Germany',
            default_value: 'United States',
        }

        const { container } = render(
            <Provider>
                <VariableComponent
                    variable={variable}
                    showEditingUI={false}
                    variableOverridesAreSet={false}
                    onChange={jest.fn()}
                />
            </Provider>
        )

        // A LemonSelect shows the value in a button; a LemonInputSelect combobox would render a text <input>
        const control = container.querySelector('[data-attr="dashboard-list-variable-select"]')
        expect(control).toBeInTheDocument()
        expect(screen.getByText('Germany')).toBeInTheDocument()
        expect(control?.querySelector('input')).not.toBeInTheDocument()
    })
})
