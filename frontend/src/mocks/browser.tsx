import { rest, setupWorker } from 'msw'
import { handlers } from '~/mocks/handlers'
import { Mocks, mocksToHandlers } from '~/mocks/utils'
import { DecoratorFunction } from '@storybook/addons'

// Default handlers ensure no request is unhandled by msw
export const worker = setupWorker(...handlers)

export const useStorybookMocks = (mocks: Mocks): void => worker.use(...mocksToHandlers(mocks))
export const mswDecorator = (mocks: Mocks): DecoratorFunction<JSX.Element> => {
    return function StoryMock(Story, { parameters }): JSX.Element {
        // merge the default mocks provided in `preview.tsx` with any provided by the story
        // allow the story to override defaults
        const mergedMocks: Mocks = {}
        Object.keys(rest).forEach((restKey) => {
            mergedMocks[restKey] = {
                ...(mocks?.[restKey] || {}),
                ...(parameters.msw?.mocks?.[restKey] || {}),
            }
        })

        useStorybookMocks(mergedMocks)
        return <Story />
    }
}

export const useFeatureFlags = (featureFlags: string[]): void => {
    ;(window as any).POSTHOG_APP_CONTEXT.persisted_feature_flags = featureFlags
}
