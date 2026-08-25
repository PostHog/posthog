import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { HogQLEditor } from './HogQLEditor'

jest.mock('lib/monaco/CodeEditorInline', () => ({
    CodeEditorInline: ({
        onChange,
        onPressCmdEnter,
    }: {
        onChange: (value: string) => void
        onPressCmdEnter?: (value: string, selectionType: 'selection' | 'full') => void
    }): JSX.Element => (
        <>
            <textarea aria-label="HogQL expression" onChange={(event) => onChange(event.target.value)} />
            <button onClick={() => onPressCmdEnter?.('', 'selection')}>Submit with shortcut</button>
        </>
    ),
}))

describe('HogQLEditor', () => {
    afterEach(cleanup)

    it('submits the full buffered expression with Cmd+Enter when Monaco has an empty selection', () => {
        const onChange = jest.fn()
        render(<HogQLEditor value="" onChange={onChange} />)

        fireEvent.change(screen.getByLabelText('HogQL expression'), {
            target: { value: 'properties.$browser' },
        })
        fireEvent.click(screen.getByText('Submit with shortcut'))

        expect(onChange).toHaveBeenCalledWith('properties.$browser')
    })

    it('blocks a full SELECT statement and explains the field takes an expression', () => {
        const onChange = jest.fn()
        const { getByLabelText, getByText } = render(<HogQLEditor value="" onChange={onChange} />)

        fireEvent.change(getByLabelText('HogQL expression'), {
            target: { value: 'SELECT * FROM events' },
        })
        fireEvent.click(getByText('Submit with shortcut'))

        expect(onChange).not.toHaveBeenCalled()
        // getByText throws if the message is missing, so reaching this asserts it rendered.
        expect(getByText(/takes a SQL expression, not a full query/)).toBeTruthy()
    })
})
