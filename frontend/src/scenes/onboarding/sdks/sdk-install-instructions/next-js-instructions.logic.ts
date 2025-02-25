import { actions, kea, path, reducers } from 'kea'

import type { nextJsInstructionsLogicType } from './next-js-instructions.logicType'

export type NextJSRouter = 'app' | 'pages'

export interface NextJsInstructionsLogicProps {
    initialRouter?: NextJSRouter
}

export const nextJsInstructionsLogic = kea<nextJsInstructionsLogicType>([
    path(['scenes', 'onboarding', 'sdks', 'nextJsInstructionsLogic']),
    actions({
        setNextJsRouter: (router) => ({ router }),
    }),
    reducers(({ props }) => ({
        nextjsRouter: [
            (props.initialRouter || 'app') as NextJSRouter,
            {
                setNextJsRouter: (_, { router }) => router,
            },
        ],
    })),
])
