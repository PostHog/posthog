import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonLabel } from './LemonLabel'

const INFO = 'Updates once daily.'

describe('LemonLabel', () => {
    afterEach(() => {
        cleanup()
    })

    it('opens the info tooltip on click without activating the labelled control', async () => {
        render(
            <div>
                <LemonLabel htmlFor="opt-in" info={INFO}>
                    Opt in
                </LemonLabel>
                <input id="opt-in" type="checkbox" />
            </div>
        )

        fireEvent.click(screen.getByText('Opt in').querySelector('svg') as SVGElement)

        expect(await screen.findByText(INFO)).toBeTruthy()
        expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false)
    })
})
