import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { HogQLEditor } from './HogQLEditor'

jest.mock('lib/monaco/CodeEditorInline', () => ({
    CodeEditorInline: ({
        onChange,
        onPressCmdEnter,
        onError,
    }: {
        onChange: (value: string) => void
        onPressCmdEnter?: (value: string, selectionType: 'selection' | 'full') => void
        onError?: (error: string | null) => void
    }): JSX.Element => (
        <>
            <textarea aria-label="HogQL expression" onChange={(event) => onChange(event.target.value)} />
            <button onClick={() => onPressCmdEnter?.('', 'selection')}>Submit with shortcut</button>
            <button onClick={() => onError?.('Error on line 1, column 1')}>Report error</button>
            <button onClick={() => onError?.(null)}>Clear error</button>
        </>
    ),
}))

describe('HogQLEditor', () => {
    afterEach(() => {
        cleanup()
    })

    it('submits the full buffered expression with Cmd+Enter when Monaco has an empty selection', () => {
        const onChange = jest.fn()
        render(<HogQLEditor value="" onChange={onChange} />)

        fireEvent.change(screen.getByLabelText('HogQL expression'), {
            target: { value: 'properties.$browser' },
        })
        fireEvent.click(screen.getByText('Submit with shortcut'))

        expect(onChange).toHaveBeenCalledWith('properties.$browser')
    })

    it('blocks the submit button while the expression has a validation error', () => {
        // LemonButton signals disabled via `aria-disabled` rather than the native attribute.
        const onChange = jest.fn()
        render(<HogQLEditor value="coalesce(properties.$current_url, properties.$screen_name)" onChange={onChange} />)

        expect(screen.getByTestId('hogql-editor-save')).toHaveAttribute('aria-disabled', 'false')

        fireEvent.click(screen.getByText('Report error'))
        expect(screen.getByTestId('hogql-editor-save')).toHaveAttribute('aria-disabled', 'true')

        fireEvent.click(screen.getByTestId('hogql-editor-save'))
        expect(onChange).not.toHaveBeenCalled()

        fireEvent.click(screen.getByText('Clear error'))
        expect(screen.getByTestId('hogql-editor-save')).toHaveAttribute('aria-disabled', 'false')
    })
})
