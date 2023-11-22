import { DecoratorFunction } from '@storybook/types'
import { rest, setupWorker } from 'msw'

import { handlers } from '~/mocks/handlers'
import { Mocks, mocksToHandlers } from '~/mocks/utils'

// Default handlers ensure no request is unhandled by msw
export const worker = setupWorker(...handlers)

export const useStorybookMocks = (mocks: Mocks): void => worker.use(...mocksToHandlers(mocks))

export const mswDecorator = (mocks: Mocks): DecoratorFunction<any> => {
    return function StoryMock(Story, { parameters }): JSX.Element {
        // merge the default mocks provided in `preview.tsx` with any provided by the story
        // allow the story to override defaults
        const mergedMocks: Mocks = {}
        for (const restMethod of Object.keys(rest)) {
            mergedMocks[restMethod] = {}
            // Ensure trailing slashes to avoid default handlers accidentally overshadowing story mocks
            for (const [path, handler] of Object.entries(parameters.msw?.mocks?.[restMethod] || {})) {
                const cleanedPath = path.replace(/\/?$/, '/')
                mergedMocks[restMethod][cleanedPath] = handler
            }
            for (const [path, handler] of Object.entries(mocks?.[restMethod] || {})) {
                const cleanedPath = path.replace(/\/?$/, '/')
                mergedMocks[restMethod][cleanedPath] = handler
            }
        }
        useStorybookMocks(mergedMocks)
        return <Story />
    }
}

export const setFeatureFlags = (featureFlags: string[]): void => {
    ;(window as any).POSTHOG_APP_CONTEXT.persisted_feature_flags = featureFlags
}
