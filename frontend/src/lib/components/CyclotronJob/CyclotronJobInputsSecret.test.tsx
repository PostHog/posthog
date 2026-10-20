import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { CyclotronJobInputs } from './CyclotronJobInputs'

describe('CyclotronJobInputs secret input', () => {
    afterEach(() => {
        cleanup()
    })

    // Workflows auto-save every input change, so a change on Edit alone overwrites the stored secret.
    it('changes nothing on Edit, and replaces the secret when the user types', () => {
        initKeaTests()
        const onInputChange = jest.fn()

        render(
            <Provider>
                <CyclotronJobInputs
                    configuration={{
                        inputs_schema: [{ key: 'port', type: 'number', label: 'Port', secret: true }],
                        inputs: { port: { value: null, secret: true } },
                    }}
                    onInputChange={onInputChange}
                    showSource={false}
                    sampleGlobalsWithInputs={null}
                />
            </Provider>
        )

        fireEvent.click(screen.getByText('Edit'))
        expect(onInputChange).not.toHaveBeenCalled()

        fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '8080' } })
        expect(onInputChange).toHaveBeenLastCalledWith('port', { value: 8080, secret: false })
    })
})
