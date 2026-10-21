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

    it('keeps the stored secret when the templating language changes before the user types', async () => {
        initKeaTests()
        const onInputChange = jest.fn()
        render(
            <Provider>
                <CyclotronJobInputs
                    configuration={{
                        inputs_schema: [{ key: 'token', type: 'string', label: 'Token', secret: true }],
                        inputs: { token: { value: null, secret: true } },
                    }}
                    onInputChange={onInputChange}
                    showSource={false}
                    sampleGlobalsWithInputs={null}
                />
            </Provider>
        )

        fireEvent.click(screen.getByText('Edit'))
        fireEvent.click(screen.getByLabelText('Supports templating - click to see available options'))
        fireEvent.click(await screen.findByText('Hog'))
        fireEvent.click(await screen.findByText('Liquid'))
        expect(onInputChange).not.toHaveBeenCalled()
    })

    it('hides the boolean mode selector while the secret is masked', () => {
        initKeaTests()
        render(
            <Provider>
                <CyclotronJobInputs
                    configuration={{
                        inputs_schema: [{ key: 'enabled', type: 'boolean', label: 'Enabled', secret: true }],
                        inputs: { enabled: { value: null, secret: true } },
                    }}
                    onInputChange={jest.fn()}
                    showSource={false}
                    sampleGlobalsWithInputs={null}
                />
            </Provider>
        )

        fireEvent.click(screen.getByText('Edit'))
        expect(screen.queryByText('Toggle')).not.toBeInTheDocument()
    })
})
