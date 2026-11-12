import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { DashboardPlacement, DashboardTile } from '~/types'

import { DashboardImageTile } from './DashboardImageTile'
import type { ImageTileImage } from './imageTileUtils'

const tile = { id: 1, layouts: {}, color: null } as DashboardTile
const image: ImageTileImage = {
    src: 'https://example.com/chart.png',
    alt: 'Signup chart',
    title: '',
    layout: 'contain',
    position: { x: 50, y: 50 },
}

const previewTrigger = (): HTMLElement => screen.getByLabelText('Signup chart')

const renderTile = (isDragging = false): void => {
    render(
        <DashboardImageTile
            tile={tile}
            image={image}
            placement={DashboardPlacement.Dashboard}
            showResizeHandles
            isDraggingRef={{ current: isDragging }}
        />
    )
}

describe('DashboardImageTile', () => {
    afterEach(cleanup)

    it('is not a native button, so the grid can still start a drag from the image', () => {
        renderTile()

        const trigger = previewTrigger()
        // The grid's drag `cancel` selector matches `button`, but not `[role="button"]`.
        expect(trigger.tagName).not.toBe('BUTTON')
        expect(trigger).toHaveAttribute('role', 'button')
        expect(trigger).toHaveAttribute('tabIndex', '0')
    })

    it.each(['Enter', ' '])('opens the preview with the %j key', (key) => {
        renderTile()

        fireEvent.keyDown(previewTrigger(), { key })

        expect(screen.getByText('Image preview')).toBeInTheDocument()
    })

    it('ignores the click that ends a drag', () => {
        renderTile(true)

        fireEvent.click(previewTrigger())

        expect(screen.queryByText('Image preview')).not.toBeInTheDocument()
    })
})
