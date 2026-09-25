import { fireEvent, render, screen } from '@testing-library/react'
import { useRef } from 'react'

import { HogQLEditor } from './HogQLEditor'

// Monaco registers the Cmd+Enter action when the editor mounts and keeps the
// callback it got then, so the mock keeps the first one too.
jest.mock('lib/monaco/CodeEditorInline', () => ({
    CodeEditorInline: ({
        onChange,
        onPressCmdEnter,
    }: {
        onChange: (value: string) => void
        onPressCmdEnter?: (value: string, selectionType: 'selection' | 'full') => void
    }): JSX.Element => {
        const mountHandler = useRef(onPressCmdEnter)
        return (
            <>
                <textarea aria-label="HogQL expression" onChange={(event) => onChange(event.target.value)} />
                <button onClick={() => mountHandler.current?.('', 'selection')}>Submit with shortcut</button>
            </>
        )
    },
}))

describe('HogQLEditor', () => {
    it('submits the expression typed after mount with Cmd+Enter', () => {
        const onChange = jest.fn()
        render(<HogQLEditor value="" onChange={onChange} />)

        fireEvent.change(screen.getByLabelText('HogQL expression'), {
            target: { value: 'properties.$browser' },
        })
        fireEvent.click(screen.getByText('Submit with shortcut'))

        expect(onChange).toHaveBeenCalledWith('properties.$browser')
    })
})
