import React from 'react'
import { setupWorker } from 'msw'
import { handlers } from '~/mocks/handlers'
import { Mocks, mocksToHandlers } from '~/mocks/utils'

// Default handlers ensure no request is unhandled by msw
export const worker = setupWorker(...handlers)

export const useStorybookMocks = (mocks: Mocks): void => worker.use(...mocksToHandlers(mocks))
export const mswDecorator = (mocks: Mocks): ((Story: () => JSX.Element) => JSX.Element) =>
    function StoryMock(Story): JSX.Element {
        useStorybookMocks(mocks)
        return <Story />
    }
