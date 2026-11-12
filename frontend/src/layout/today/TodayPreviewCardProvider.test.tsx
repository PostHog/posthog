import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { TodayPreviewCardProvider } from './TodayPreviewCardProvider'
import { TodayExplainerPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'

const preview = (label: string): TodayExplainerPreview => ({
    kind: 'explainer',
    label,
    icon: <span />,
    description: `${label} description`,
})
const broadcasts = preview('Broadcasts')
const playground = preview('Playground')

describe('TodayPreviewCardProvider', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    const renderRows = (): void => {
        render(
            <TodayPreviewCardProvider>
                <TodayPreviewTrigger payload={broadcasts}>
                    <button type="button">Broadcasts row</button>
                </TodayPreviewTrigger>
                <TodayPreviewTrigger payload={playground}>
                    <button type="button">Playground row</button>
                </TodayPreviewTrigger>
            </TodayPreviewCardProvider>
        )
    }

    const hover = async (rowText: string): Promise<void> => {
        const trigger = screen.getByText(rowText).parentElement as HTMLElement
        fireEvent.pointerEnter(trigger)
        fireEvent.mouseEnter(trigger)
        fireEvent.mouseMove(trigger)
        await act(async () => {
            jest.advanceTimersByTime(1000)
        })
    }

    const rest = async (rowText: string): Promise<void> => {
        fireEvent.mouseMove(screen.getByText(rowText).parentElement as HTMLElement)
        await act(async () => {
            jest.advanceTimersByTime(1000)
        })
    }

    const leave = async (rowText: string): Promise<void> => {
        const trigger = screen.getByText(rowText).parentElement as HTMLElement
        fireEvent.pointerLeave(trigger)
        fireEvent.mouseLeave(trigger)
        await act(async () => {
            jest.advanceTimersByTime(1000)
        })
    }

    const click = async (rowText: string): Promise<void> => {
        fireEvent.click(screen.getByText(rowText))
        await act(async () => {
            jest.advanceTimersByTime(1000)
        })
    }

    const cardShown = (label: string): boolean => screen.queryByText(`${label} description`) !== null

    it('closes the card on a click and keeps it shut until the pointer leaves the row and comes back', async () => {
        renderRows()

        await hover('Broadcasts row')
        expect(cardShown('Broadcasts')).toBe(true)

        await click('Broadcasts row')
        expect(cardShown('Broadcasts')).toBe(false)

        await rest('Broadcasts row')
        expect(cardShown('Broadcasts')).toBe(false)

        await leave('Broadcasts row')
        await hover('Broadcasts row')
        expect(cardShown('Broadcasts')).toBe(true)
    })

    it('opens again from the keyboard once focus has left a row activated with Enter', async () => {
        renderRows()
        const broadcastsRow = screen.getByText('Broadcasts row')

        await click('Broadcasts row')
        fireEvent.blur(broadcastsRow)
        fireEvent.focus(screen.getByText('Playground row'))
        fireEvent.focus(broadcastsRow)
        await act(async () => {
            jest.advanceTimersByTime(1000)
        })
        expect(cardShown('Broadcasts')).toBe(true)
    })

    it('opens on the first hover of a row clicked from a search list, which the pointer never visited', async () => {
        renderRows()

        await click('Broadcasts row')
        await hover('Broadcasts row')
        expect(cardShown('Broadcasts')).toBe(true)
    })

    it('refuses the pending open of a row clicked before its card appeared, but still opens other rows', async () => {
        renderRows()

        const trigger = screen.getByText('Broadcasts row').parentElement as HTMLElement
        fireEvent.pointerEnter(trigger)
        fireEvent.mouseEnter(trigger)
        fireEvent.mouseMove(trigger)
        await click('Broadcasts row')
        expect(cardShown('Broadcasts')).toBe(false)

        await leave('Broadcasts row')
        await hover('Playground row')
        expect(cardShown('Playground')).toBe(true)
    })
})
