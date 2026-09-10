import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'

import { displayOptionsToMenuItems, DisplayOptionTab } from './insightDisplayOptions'

function Curve(): JSX.Element {
    return <div>Curve</div>
}

function Legend(): JSX.Element {
    return <div>Show legend</div>
}

describe('displayOptionsToMenuItems', () => {
    const tabs: DisplayOptionTab[] = [
        {
            key: 'general',
            label: 'General',
            count: 0,
            sections: [{ key: 'display', dataAttr: 'options-display-section', items: [Legend] }],
        },
        {
            key: 'lines',
            label: 'Lines',
            count: 0,
            sections: [{ key: 'style', title: 'Style', items: [Curve] }],
        },
    ]

    afterEach(() => {
        cleanup()
    })

    it('gives every section a header, falling back to the tab label when it has none', () => {
        render(<LemonMenuOverlay items={displayOptionsToMenuItems(tabs)} />)

        expect(screen.getByText('General')).toBeInTheDocument()
        expect(screen.getByText('Style')).toBeInTheDocument()
        expect(screen.getByText('Show legend')).toBeInTheDocument()
        expect(screen.getByText('Curve')).toBeInTheDocument()
    })

    // LemonMenu renders a function label as a component type, so wrapping each control in a fresh
    // arrow would remount it — and drop any uncommitted input draft — on every tile render.
    it('keeps each control mounted when the tile re-renders', () => {
        const { rerender } = render(<LemonMenuOverlay items={displayOptionsToMenuItems(tabs)} />)
        const curve = screen.getByText('Curve')

        rerender(<LemonMenuOverlay items={displayOptionsToMenuItems(tabs)} />)

        expect(screen.getByText('Curve')).toBe(curve)
    })
})
