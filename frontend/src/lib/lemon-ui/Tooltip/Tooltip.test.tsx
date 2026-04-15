import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { kea, path, resetContext } from 'kea'
import { Form, forms } from 'kea-forms'

import { LemonField } from '../LemonField/LemonField'
import { LemonLabel } from '../LemonLabel/LemonLabel'
import { Tooltip } from './Tooltip'

const findOpenTooltipText = (): string | null => {
    const popup = document.querySelector('.Tooltip__popup[data-open]')
    return popup?.textContent ?? null
}

describe('Tooltip', () => {
    afterEach(() => {
        cleanup()
        // Base UI portals can leave nodes outside the RTL render container
        document.body.innerHTML = ''
    })

    it('shows tooltip when hovering a trigger', async () => {
        const user = userEvent.setup()
        render(
            <Tooltip title="hello tooltip">
                <button data-attr="trigger">trigger</button>
            </Tooltip>
        )
        const trigger = screen.getByTestId('trigger')
        await act(async () => {
            await user.hover(trigger)
        })
        await waitFor(
            () => {
                expect(findOpenTooltipText()).toContain('hello tooltip')
            },
            { timeout: 2000 }
        )
    })

    it('shows tooltip from LemonLabel info prop', async () => {
        const user = userEvent.setup()
        render(<LemonLabel info="my lemon label tooltip">lemon label text</LemonLabel>)
        const label = screen.getByText('lemon label text').closest('label')
        expect(label).not.toBeNull()
        const svg = label!.querySelector('svg')
        expect(svg).not.toBeNull()
        await act(async () => {
            await user.hover(svg!)
        })
        await waitFor(
            () => {
                expect(findOpenTooltipText()).toContain('my lemon label tooltip')
            },
            { timeout: 2000 }
        )
    })

    it('shows tooltip from LemonField within a Kea form (like HogFunctionFilters)', async () => {
        resetContext({ createStore: true })
        const testFormLogic = kea([
            path(['tests', 'Tooltip', 'form']),
            forms(() => ({
                myForm: {
                    defaults: { masking: null },
                    submit: () => {},
                },
            })),
        ])
        testFormLogic.mount()

        const user = userEvent.setup()
        render(
            <Form logic={testFormLogic} formKey="myForm">
                <LemonField name="masking" label="Trigger options" info="my trigger options tooltip">
                    <span>content</span>
                </LemonField>
            </Form>
        )
        const label = screen.getByText('Trigger options').closest('label')
        expect(label).not.toBeNull()
        const svg = label!.querySelector('svg')
        expect(svg).not.toBeNull()
        await act(async () => {
            await user.hover(svg!)
        })
        await waitFor(
            () => {
                expect(findOpenTooltipText()).toContain('my trigger options tooltip')
            },
            { timeout: 2000 }
        )
    })

    it('shows tooltip from LemonField.Pure info prop', async () => {
        const user = userEvent.setup()
        render(
            <LemonField.Pure label="Pure field label" info="pure field info">
                <span>content</span>
            </LemonField.Pure>
        )
        const label = screen.getByText('Pure field label').closest('label')
        expect(label).not.toBeNull()
        const svg = label!.querySelector('svg')
        expect(svg).not.toBeNull()
        await act(async () => {
            await user.hover(svg!)
        })
        await waitFor(
            () => {
                expect(findOpenTooltipText()).toContain('pure field info')
            },
            { timeout: 2000 }
        )
    })
})
