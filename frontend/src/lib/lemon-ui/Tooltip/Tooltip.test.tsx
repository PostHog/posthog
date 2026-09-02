import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { Tooltip } from './Tooltip'

const TITLE = 'Released 2 years ago. Upgrade recommended.'

function renderTooltip(props: { openOnClick?: boolean } = {}): void {
    render(
        <div>
            <Tooltip title={TITLE} delayMs={0} {...props}>
                <span>Outdated</span>
            </Tooltip>
            <button>Elsewhere</button>
        </div>
    )
}

describe('Tooltip', () => {
    afterEach(() => {
        cleanup()
    })

    it('opens on hover', async () => {
        renderTooltip()

        fireEvent.pointerEnter(screen.getByText('Outdated'), { pointerType: 'mouse' })
        fireEvent.mouseEnter(screen.getByText('Outdated'))

        expect(await screen.findByText(TITLE)).toBeTruthy()
    })

    it('does not open on click by default', async () => {
        renderTooltip()

        fireEvent.click(screen.getByText('Outdated'))

        await waitFor(() => expect(screen.queryByText(TITLE)).toBeNull())
    })

    it('opens on click when openOnClick is set', async () => {
        renderTooltip({ openOnClick: true })

        fireEvent.click(screen.getByText('Outdated'))

        expect(await screen.findByText(TITLE)).toBeTruthy()
    })

    it('still opens on hover when openOnClick is set', async () => {
        renderTooltip({ openOnClick: true })

        fireEvent.pointerEnter(screen.getByText('Outdated'), { pointerType: 'mouse' })
        fireEvent.mouseEnter(screen.getByText('Outdated'))

        expect(await screen.findByText(TITLE)).toBeTruthy()
    })

    // Not covered here: that clicking a tooltip you are already hovering doesn't dismiss it (the
    // `closeOnClick={!openOnClick}` half of the fix). Base UI dismisses on pointerdown via a real
    // pointer-event listener that jsdom never triggers, so it can only be checked in a browser.

    it('closes on Escape once opened by click', async () => {
        renderTooltip({ openOnClick: true })

        fireEvent.click(screen.getByText('Outdated'))
        expect(await screen.findByText(TITLE)).toBeTruthy()

        fireEvent.keyDown(document, { key: 'Escape' })

        await waitFor(() => expect(screen.queryByText(TITLE)).toBeNull())
    })

    it('closes on a press outside once opened by click', async () => {
        renderTooltip({ openOnClick: true })

        fireEvent.click(screen.getByText('Outdated'))
        expect(await screen.findByText(TITLE)).toBeTruthy()

        fireEvent.pointerDown(screen.getByText('Elsewhere'))
        fireEvent.mouseDown(screen.getByText('Elsewhere'))

        await waitFor(() => expect(screen.queryByText(TITLE)).toBeNull())
    })

    it('dismisses on scroll outside the tooltip', async () => {
        renderTooltip()

        fireEvent.pointerEnter(screen.getByText('Outdated'), { pointerType: 'mouse' })
        fireEvent.mouseEnter(screen.getByText('Outdated'))
        expect(await screen.findByText(TITLE)).toBeTruthy()

        fireEvent.scroll(window)

        await waitFor(() => expect(screen.queryByText(TITLE)).toBeNull())
    })

    it('does not dismiss on scroll inside the tooltip', async () => {
        renderTooltip()

        fireEvent.pointerEnter(screen.getByText('Outdated'), { pointerType: 'mouse' })
        fireEvent.mouseEnter(screen.getByText('Outdated'))
        const title = await screen.findByText(TITLE)

        fireEvent.scroll(title)

        expect(screen.getByText(TITLE)).toBeTruthy()
    })

    it('does not dismiss a controlled tooltip on scroll', async () => {
        render(
            <div>
                <Tooltip title={TITLE} visible>
                    <span>Outdated</span>
                </Tooltip>
            </div>
        )

        expect(await screen.findByText(TITLE)).toBeTruthy()

        fireEvent.scroll(window)

        expect(screen.getByText(TITLE)).toBeTruthy()
    })
})
