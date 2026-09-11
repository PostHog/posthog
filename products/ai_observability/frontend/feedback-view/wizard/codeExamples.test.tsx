import '@testing-library/jest-dom'

import { act, fireEvent, render, screen } from '@testing-library/react'
import * as React from 'react'
import { JsxEmit, ModuleKind, transpileModule } from 'typescript'

import { getReactExample } from './codeExamples'

describe('React feedback example', () => {
    it.each([false, true])('waits for its survey before accepting feedback (follow-up: %s)', (followUpEnabled) => {
        let onSurveysLoaded: (surveys: { id: string }[]) => void = () => {}
        const unsubscribe = jest.fn()
        const respond = jest.fn()
        const posthog = {
            onSurveysLoaded: (callback: typeof onSurveysLoaded) => {
                onSurveysLoaded = callback
                return unsubscribe
            },
        }
        const modules: Record<string, unknown> = {
            react: React,
            '@posthog/react': { usePostHog: () => posthog },
            '@posthog/react/surveys': {
                useThumbSurvey: () => ({ respond, response: null, triggerRef: () => {} }),
            },
        }
        const { outputText } = transpileModule(getReactExample({ surveyId: 'feedback-survey', followUpEnabled }), {
            compilerOptions: { jsx: JsxEmit.React, module: ModuleKind.CommonJS },
            fileName: 'feedback-example.tsx',
        })
        const Example: React.ComponentType<{ traceId: string }> = new Function(
            'require',
            'exports',
            'React',
            'ChatBubble',
            `${outputText}\nreturn HedgehogBotResponse`
        )(
            (name: string) => modules[name],
            {},
            React,
            ({ children }: React.PropsWithChildren) => <div>{children}</div>
        )

        const { unmount } = render(<Example traceId="example-trace" />)
        const up = screen.getByText('👍')
        const down = screen.getByText('👎')

        expect(up).toBeDisabled()
        expect(down).toBeDisabled()
        fireEvent.click(up)
        expect(respond).not.toHaveBeenCalled()
        expect(screen.getByText('Loading feedback...')).toBeInTheDocument()

        act(() => onSurveysLoaded([]))
        expect(up).toBeDisabled()
        expect(screen.getByText('Feedback is unavailable. Refresh the page to try again.')).toBeInTheDocument()

        act(() => onSurveysLoaded([{ id: 'another-survey' }]))
        expect(up).toBeDisabled()

        act(() => onSurveysLoaded([{ id: 'feedback-survey' }]))
        expect(up).toBeEnabled()
        expect(down).toBeEnabled()
        expect(screen.queryByText('Loading feedback...')).not.toBeInTheDocument()
        expect(screen.queryByText('Feedback is unavailable. Refresh the page to try again.')).not.toBeInTheDocument()

        fireEvent.click(up)
        expect(respond).toHaveBeenCalledTimes(1)
        expect(respond).toHaveBeenCalledWith('up')

        unmount()
        expect(unsubscribe).toHaveBeenCalledTimes(1)
    })
})
