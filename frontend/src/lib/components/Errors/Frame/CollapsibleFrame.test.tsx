import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { initKeaTests } from '~/test/init'

import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { CollapsibleFrame } from './CollapsibleFrame'

const baseFrame: ErrorTrackingStackFrame = {
    raw_id: 'frame-1',
    mangled_name: 'loadFrameContexts',
    line: 11,
    column: 5,
    source: 'src/FrameLoader.ts',
    in_app: true,
    resolved_name: 'loadFrameContexts',
    lang: 'typescript',
    resolved: true,
    resolve_failure: null,
    module: null,
}

const noContextRecord: ErrorTrackingStackFrameRecord = {
    id: 'record-1',
    raw_id: 'frame-1',
    created_at: '2024-01-01T00:00:00Z',
    resolved: true,
    context: null,
    contents: baseFrame,
    symbol_set_ref: 'https://static.example.com/chunks.js',
    release: null,
}

function renderFrame(frame: ErrorTrackingStackFrame, initialExpanded = false): void {
    function Harness(): JSX.Element {
        const [expanded, setExpanded] = useState(initialExpanded)
        return (
            <BindLogic logic={errorPropertiesLogic} props={{ properties: {}, id: 'test' }}>
                <CollapsibleFrame
                    frame={frame}
                    record={noContextRecord}
                    recordLoading={false}
                    expanded={expanded}
                    onExpandedChange={setExpanded}
                />
            </BindLogic>
        )
    }
    render(<Harness />)
}

describe('CollapsibleFrame', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    it('lets a frame without source code expand to explain why', async () => {
        renderFrame(baseFrame)

        const trigger = screen.getByText(baseFrame.resolved_name!).closest('button')
        expect(trigger).not.toBeDisabled()

        await userEvent.click(trigger!)

        expect(screen.getByText(/source map was not uploaded/i)).toBeInTheDocument()
        expect(screen.getByRole('link', { name: /upload source maps/i })).toHaveAttribute(
            'href',
            'https://posthog.com/docs/error-tracking/upload-source-maps'
        )
    })

    it.each([
        ['vendor', { ...baseFrame, in_app: false }, /vendor frame/i],
        ['unresolved', { ...baseFrame, resolved: false }, /not resolved yet/i],
        ['resolved without source', baseFrame, /source map was not uploaded/i],
        ['unidentified', { ...baseFrame, resolved_name: null, mangled_name: '', source: null }, /could not identify/i],
    ])('explains a %s frame', (_name, frame, matcher) => {
        renderFrame(frame, true)
        expect(screen.getByText(matcher)).toBeInTheDocument()
    })
})
