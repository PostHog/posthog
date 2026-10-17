import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Component, type ReactNode } from 'react'

import { EventType } from '~/types'

import { ExpandedEventRow } from './ExpandedEventRow'

jest.mock('scenes/activity/explore/EventDetails', () => {
    throw new TypeError('Failed to fetch dynamically imported module: /static/EventDetails.js')
})

class TableErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
    override state = { failed: false }

    static getDerivedStateFromError(): { failed: boolean } {
        return { failed: true }
    }

    override render(): ReactNode {
        return this.state.failed ? <div>table replaced by an error</div> : this.props.children
    }
}

describe('ExpandedEventRow', () => {
    let consoleErrorSpy: jest.SpyInstance
    let consoleWarnSpy: jest.SpyInstance

    beforeEach(() => {
        // The query's ErrorBoundary is nearer than the scene's, so a stale chunk that escaped this
        // boundary would replace the whole table. Pretend a reload already ran, so the guard makes
        // the boundary surface the error instead of reloading again.
        window.localStorage.setItem('posthog-chunk-reload-at', String(Date.now()))
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {})
    })

    afterEach(() => {
        window.localStorage.clear()
        consoleErrorSpy.mockRestore()
        consoleWarnSpy.mockRestore()
        cleanup()
    })

    it('keeps the table on screen when the event details chunk fails after a reload', async () => {
        render(
            <TableErrorBoundary>
                <ExpandedEventRow event={{ id: 'event-1' } as EventType} />
            </TableErrorBoundary>
        )

        expect(await screen.findByText(/Couldn't load the event details/, {}, { timeout: 3000 })).toBeInTheDocument()
        expect(screen.queryByText('table replaced by an error')).not.toBeInTheDocument()
    })
})
