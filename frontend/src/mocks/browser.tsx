import { DecoratorFunction } from '@storybook/types'
import { rest, setupWorker } from 'msw'

import { handlers } from '~/mocks/handlers'
import { MockSignature, Mocks, mocksToHandlers } from '~/mocks/utils'

// Default handlers ensure no request is unhandled by msw
export const worker: ReturnType<typeof setupWorker> = setupWorker(...handlers)

export const useStorybookMocks = (mocks: Mocks): void => worker.use(...mocksToHandlers(mocks))

export const mswDecorator = (mocks: Mocks): DecoratorFunction<any> => {
    return function StoryMock(Story, { parameters }): JSX.Element {
        // merge the default mocks provided in `preview.tsx` with any provided by the story
        // allow the story to override defaults
        const mergedMocks: Mocks = {}
        const restKeys = Object.keys(rest) as Array<keyof typeof rest>
        for (const restMethod of restKeys) {
            mergedMocks[restMethod] = {}
            const storyMethodMocks = (parameters.msw?.mocks?.[restMethod] || {}) as Record<string, MockSignature>
            // Ensure trailing slashes to avoid default handlers accidentally overshadowing story mocks
            for (const [path, handler] of Object.entries(storyMethodMocks)) {
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
