import '@testing-library/jest-dom'

import { act, render, screen, waitFor } from '@testing-library/react'
import * as React from 'react'

const ReactActual = jest.requireActual<typeof React>('react')

jest.mock('lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown', () => ({
    LemonTextAreaMarkdown: (): JSX.Element => <div data-attr="text-card-edit-area">legacy</div>,
}))

jest.mock('lib/components/Cards/TextCard/TextCardMarkdownEditor', () => ({
    TextCardMarkdownEditor: (): JSX.Element => <div data-attr="text-card-rich-editor">rich</div>,
}))

import { TextCardModalBodyField } from './TextCardModalBodyField'

describe('TextCardModalBodyField', () => {
    let lazySpy: jest.SpyInstance

    beforeEach(() => {
        jest.useFakeTimers()
        lazySpy = jest.spyOn(React, 'lazy').mockImplementation((importFn) =>
            ReactActual.lazy(
                () =>
                    new Promise((resolve) => {
                        setTimeout(() => {
                            void importFn().then(resolve)
                        }, 50)
                    })
            )
        )
    })

    afterEach(() => {
        lazySpy.mockRestore()
        jest.useRealTimers()
    })

    it('shows Suspense fallback while the editor chunk loads, then the legacy editor', async () => {
        render(<TextCardModalBodyField shouldUseLegacyMarkdownEditor value="" onChange={jest.fn()} />)

        expect(screen.getByTestId('text-card-editor-suspense-fallback')).toBeInTheDocument()
        expect(screen.queryByTestId('text-card-edit-area')).not.toBeInTheDocument()

        await act(async () => {
            jest.advanceTimersByTime(50)
        })

        await waitFor(
            () => {
                expect(screen.getByTestId('text-card-edit-area')).toBeInTheDocument()
            },
            { advanceTimers: jest.advanceTimersByTime }
        )
        expect(screen.queryByTestId('text-card-editor-suspense-fallback')).not.toBeInTheDocument()
    })

    it('shows fallback then the rich editor when not legacy', async () => {
        render(<TextCardModalBodyField shouldUseLegacyMarkdownEditor={false} value="" onChange={jest.fn()} />)

        expect(screen.getByTestId('text-card-editor-suspense-fallback')).toBeInTheDocument()

        await act(async () => {
            jest.advanceTimersByTime(50)
        })

        await waitFor(
            () => {
                expect(screen.getByTestId('text-card-rich-editor')).toBeInTheDocument()
            },
            { advanceTimers: jest.advanceTimersByTime }
        )
    })
})
