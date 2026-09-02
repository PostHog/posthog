import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { Tooltip } from './Tooltip'

describe('Tooltip', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('does not mount Base UI trigger/root for idle uncontrolled tooltips', () => {
        render(
            <Tooltip title="Helpful context">
                <button>Hover me</button>
            </Tooltip>
        )

        const button = screen.getByRole('button', { name: 'Hover me' })

        expect(button).not.toHaveAttribute('data-base-ui-tooltip-trigger')
        expect(screen.queryByText('Helpful context')).not.toBeInTheDocument()

        fireEvent.mouseEnter(button)
        act(() => jest.advanceTimersByTime(399))

        expect(button).not.toHaveAttribute('data-base-ui-tooltip-trigger')
        expect(screen.queryByText('Helpful context')).not.toBeInTheDocument()

        act(() => jest.advanceTimersByTime(1))

        expect(screen.getByRole('button', { name: 'Hover me' })).toHaveAttribute('data-base-ui-tooltip-trigger')
        expect(screen.getByText('Helpful context')).toBeInTheDocument()
    })

    it.each([
        {
            name: 'controlled',
            props: { visible: false },
        },
        {
            name: 'interactive',
            props: { interactive: true },
        },
        {
            name: 'doc link',
            props: { docLink: 'https://posthog.com/docs' },
        },
    ])('mounts Base UI trigger/root immediately for $name tooltips', ({ props }) => {
        render(
            <Tooltip title="Helpful context" {...props}>
                <button>Open me</button>
            </Tooltip>
        )

        expect(screen.getByRole('button', { name: 'Open me' })).toHaveAttribute('data-base-ui-tooltip-trigger')
    })
})
