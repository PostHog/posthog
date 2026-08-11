import { fireEvent, render, screen } from '@testing-library/react'

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
    it('submits the full buffered expression with Cmd+Enter when Monaco has an empty selection', () => {
        const onChange = jest.fn()
        render(<HogQLEditor value="" onChange={onChange} />)

        fireEvent.change(screen.getByLabelText('HogQL expression'), {
            target: { value: 'properties.$browser' },
        })
        fireEvent.click(screen.getByText('Submit with shortcut'))

        expect(onChange).toHaveBeenCalledWith('properties.$browser')
    })
})
