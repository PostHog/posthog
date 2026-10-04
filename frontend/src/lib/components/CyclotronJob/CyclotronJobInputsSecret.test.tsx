import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { CyclotronJobInputType } from '~/types'

import { CyclotronJobInputs } from './CyclotronJobInputs'

describe('CyclotronJobInputs secret input', () => {
    afterEach(() => {
        cleanup()
    })

    // Workflows auto-save every input change, so a change on Edit alone overwrites the stored secret.
    it('changes nothing on Edit, replaces the secret when the user types, and masks it again after save', () => {
        initKeaTests()
        const onInputChange = jest.fn()
        const renderInputs = (port: CyclotronJobInputType): JSX.Element => (
            <Provider>
                <CyclotronJobInputs
                    configuration={{
                        inputs_schema: [{ key: 'port', type: 'number', label: 'Port', secret: true }],
                        inputs: { port },
                    }}
                    onInputChange={onInputChange}
                    showSource={false}
                    sampleGlobalsWithInputs={null}
                />
            </Provider>
        )

        const { rerender } = render(renderInputs({ value: null, secret: true }))

        fireEvent.click(screen.getByText('Edit'))
        expect(onInputChange).not.toHaveBeenCalled()

        fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '8080' } })
        expect(onInputChange).toHaveBeenLastCalledWith('port', { value: 8080, secret: false })

        rerender(renderInputs({ value: 8080, secret: false }))
        rerender(renderInputs({ value: null, secret: true }))
        expect(screen.getByText('This value is secret and is not displayed here.')).toBeInTheDocument()
        expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
    })
})
