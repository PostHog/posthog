import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Component, type ReactNode } from 'react'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import { AIObservabilityGlobalColumnCell } from './AIObservabilityGlobalColumnCell'

jest.mock('./aiObservabilityColumnRenderers', () => {
    throw new TypeError('Failed to fetch dynamically imported module: /static/aiObservabilityColumnRenderers.js')
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

const query: DataTableNode = { kind: NodeKind.DataTableNode, source: { kind: NodeKind.EventsQuery, select: ['*'] } }

describe('AIObservabilityGlobalColumnCell', () => {
    let consoleErrorSpy: jest.SpyInstance
    let consoleWarnSpy: jest.SpyInstance

    beforeEach(() => {
        // Another cell's boundary already reloaded for this chunk, so the guard stops a second reload.
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

    it('keeps the table on screen when the renderer chunk fails after a reload', async () => {
        render(
            <TableErrorBoundary>
                <AIObservabilityGlobalColumnCell
                    rendererKey="properties.$ai_trace_id"
                    columnName="properties.$ai_trace_id"
                    query={query}
                    record={{}}
                    recordIndex={0}
                    rowCount={1}
                    value="trace-1"
                />
            </TableErrorBoundary>
        )

        expect(await screen.findByText('Error', {}, { timeout: 3000 })).toBeInTheDocument()
        expect(screen.queryByText('table replaced by an error')).not.toBeInTheDocument()
    })
})
