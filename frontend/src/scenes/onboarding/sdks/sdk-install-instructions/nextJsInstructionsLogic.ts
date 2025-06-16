import { actions, kea, path, reducers } from 'kea'

import type { nextJsInstructionsLogicType } from './nextJsInstructionsLogicType'

export type NextJSRouter = 'instrumentation-client' | 'app' | 'pages'

export interface NextJsInstructionsLogicProps {
    initialRouter?: NextJSRouter
}

export const nextJsInstructionsLogic = kea<nextJsInstructionsLogicType>([
    path(['scenes', 'onboarding', 'sdks', 'nextJsInstructionsLogic']),
    actions({
        setNextJsRouter: (router) => ({ router }),
    }),
    reducers(({ props }) => ({
        nextJsRouter: [
            (props.initialRouter || 'instrumentation-client') as NextJSRouter,
            {
                setNextJsRouter: (_, { router }) => router,
            },
        ],
    })),
])
