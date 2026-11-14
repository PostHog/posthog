import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { CollapsibleFrameHeader } from './CollapsibleFrameHeader'

const baseFrame: ErrorTrackingStackFrame = {
    raw_id: 'frame-test-1',
    mangled_name: 'handleClick',
    line: 42,
    column: 12,
    source: 'src/components/Button.tsx',
    in_app: true,
    resolved_name: 'handleClick',
    lang: 'typescript',
    resolved: true,
    resolve_failure: null,
    module: null,
}

const baseRecord: ErrorTrackingStackFrameRecord = {
    id: 'record-test-1',
    raw_id: 'frame-test-1',
    created_at: '2026-01-01T00:00:00Z',
    resolved: true,
    context: {
        before: [],
        line: { number: 42, line: 'const handleClick = () => {}' },
        after: [],
    },
    contents: baseFrame,
    symbol_set_ref: null,
    release: null,
}

describe('CollapsibleFrameHeader', () => {
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    function renderHeader(
        props: {
            frame?: ErrorTrackingStackFrame
            record?: ErrorTrackingStackFrameRecord
            recordLoading?: boolean
            expanded?: boolean
        } = {}
    ): ReturnType<typeof render> {
        return render(
            <BindLogic logic={errorPropertiesLogic} props={{ properties: {}, id: 'test' }}>
                <CollapsibleFrameHeader
                    frame={props.frame ?? baseFrame}
                    record={props.record ?? baseRecord}
                    recordLoading={props.recordLoading ?? false}
                    expanded={props.expanded ?? false}
                />
            </BindLogic>
        )
    }

    it('renders stack frame function and source with selectable classes', () => {
        renderHeader()

        const functionEl = screen.getByText('handleClick')
        const sourceEl = screen.getByText('src/components/Button.tsx@42:12')
        const trigger = functionEl.closest('button')

        expect(functionEl).toBeInTheDocument()
        expect(functionEl).toHaveClass('frame-function')
        expect(sourceEl).toBeInTheDocument()
        expect(sourceEl).toHaveClass('frame-source')
        expect(trigger).toHaveClass('select-text')
        expect(trigger).toHaveClass('collapsible-frame-header')
    })

    it('suppresses toggle click when active text selection is present', () => {
        renderHeader()

        const trigger = screen.getByText('handleClick').closest('button')!

        // Mock window.getSelection returning selected text
        jest.spyOn(window, 'getSelection').mockReturnValue({
            toString: () => 'handleClick',
        } as Selection)

        const event = new MouseEvent('click', { bubbles: true, cancelable: true })
        fireEvent(trigger, event)

        expect(event.defaultPrevented).toBe(true)
    })

    it('allows toggle click when no text selection is present', () => {
        renderHeader()

        const trigger = screen.getByText('handleClick').closest('button')!

        // Mock window.getSelection returning empty selection
        jest.spyOn(window, 'getSelection').mockReturnValue({
            toString: () => '',
        } as Selection)

        const event = new MouseEvent('click', { bubbles: true, cancelable: true })
        fireEvent(trigger, event)

        expect(event.defaultPrevented).toBe(false)
    })
})
