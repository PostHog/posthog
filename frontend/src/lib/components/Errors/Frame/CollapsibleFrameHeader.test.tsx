import { fireEvent, render, screen } from '@testing-library/react'

import { ErrorTrackingStackFrame, ErrorTrackingStackFrameRecord } from '../types'
import { CollapsibleFrameHeader } from './CollapsibleFrameHeader'

jest.mock('kea', () => {
    const actual = jest.requireActual('kea')
    return {
        ...actual,
        useValues: () => ({
            getFrameFingerprint: () => undefined,
            getSourceDataForFrame: () => undefined,
        }),
    }
})

jest.mock('../errorPropertiesLogic', () => ({ errorPropertiesLogic: {} }))

jest.mock('../FingerprintRecordPartDisplay', () => ({
    FingerprintRecordPartDisplay: () => null,
}))

jest.mock('./FrameDropDownMenu', () => ({
    FrameDropDownMenu: ({ children }: { children: React.ReactNode }) => <button type="button">{children}</button>,
}))

const frame: ErrorTrackingStackFrame = {
    raw_id: 'frame-1',
    mangled_name: 'my_function',
    line: 42,
    column: 3,
    source: 'src/app/main.py',
    in_app: true,
    resolved_name: 'my_function',
    lang: 'python',
    resolved: true,
    resolve_failure: null,
    module: null,
}

const record = { context: { before: [], line: null, after: [] } } as unknown as ErrorTrackingStackFrameRecord

describe('CollapsibleFrameHeader', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('renders the function and source outside a button so they can be selected and copied', () => {
        render(
            <CollapsibleFrameHeader frame={frame} record={record} recordLoading={false} expanded={false} />
        )

        const functionName = screen.getByText('my_function')
        expect(functionName.closest('button')).toBeNull()
        expect(functionName.classList.contains('select-text')).toBe(true)

        const source = screen.getByText('src/app/main.py@42:3')
        expect(source.closest('button')).toBeNull()
        expect(source.classList.contains('select-text')).toBe(true)
    })

    it('renders selectable text even when the frame cannot be expanded', () => {
        render(<CollapsibleFrameHeader frame={frame} recordLoading={false} expanded={false} />)

        const functionName = screen.getByText('my_function')
        expect(functionName.closest('button')).toBeNull()
        expect(functionName.closest('[role="button"]')).toBeNull()
    })

    it('toggles the frame when the header is clicked', () => {
        const onExpandedChange = jest.fn()
        render(
            <CollapsibleFrameHeader
                frame={frame}
                record={record}
                recordLoading={false}
                expanded={false}
                onExpandedChange={onExpandedChange}
            />
        )

        const header = screen.getByText('my_function').closest('[role="button"]')
        expect(header).not.toBeNull()
        fireEvent.click(header!)
        expect(onExpandedChange).toHaveBeenCalledWith(true)
    })

    it('does not toggle when the user has selected text', () => {
        const onExpandedChange = jest.fn()
        jest.spyOn(window, 'getSelection').mockReturnValue({
            toString: () => 'my_function',
        } as Selection)
        render(
            <CollapsibleFrameHeader
                frame={frame}
                record={record}
                recordLoading={false}
                expanded={false}
                onExpandedChange={onExpandedChange}
            />
        )

        fireEvent.click(screen.getByText('my_function').closest('[role="button"]')!)
        expect(onExpandedChange).not.toHaveBeenCalled()
    })
})
