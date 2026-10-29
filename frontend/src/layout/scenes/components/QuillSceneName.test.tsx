import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { QuillSceneName } from './QuillSceneName'

describe('QuillSceneName', () => {
    afterEach(() => {
        cleanup()
    })

    // Guards the name's only visible edit affordance: the hover fill says nothing until the pointer
    // is already on the name, so a rename nobody can discover is a rename nobody makes.
    test('shows the edit pencil beside an editable name', () => {
        render(<QuillSceneName name="Meta CAPI" onChange={jest.fn()} canEdit />)

        expect(screen.getByRole('button', { name: 'Meta CAPI' }).querySelector('svg')).toBeInTheDocument()
    })
})
