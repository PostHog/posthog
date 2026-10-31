import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ScreenEditorCard } from './ScreenEditorCard'

describe('ScreenEditorCard', () => {
    afterEach(() => {
        cleanup()
    })

    it.each(['Intro screen', 'Confirmation screen'])('names the %s toggle after the card', (title) => {
        render(
            <ScreenEditorCard title={title} enabled={false} onToggle={jest.fn()}>
                <span />
            </ScreenEditorCard>
        )

        expect(screen.getByLabelText(title)).toHaveAttribute('role', 'switch')
    })
})
