import { actions, kea, listeners, path, props, reducers, selectors } from 'kea'

import type { exceptionCardLogicType } from './exceptionCardLogicType'

export interface ExceptionCardLogicProps {
    loading: boolean
}

export const exceptionCardLogic = kea<exceptionCardLogicType>([
    path(() => ['scenes', 'error-tracking', 'exceptionCardLogic']),
    props({} as ExceptionCardLogicProps),

    actions({
        setShowDetails: (showDetails: boolean) => ({ showDetails }),
        setShowAsText: (showAsText: boolean) => ({ showAsText }),
        setShowContext: (showContext: boolean) => ({ showContext }),
        setShowAllFrames: (showAllFrames: boolean) => ({ showAllFrames }),
    }),

    reducers({
        showDetails: [
            false,
            { persist: true },
            {
                setShowDetails: (_, { showDetails }: { showDetails: boolean }) => showDetails,
            },
        ],
        showAsText: [
            false,
            { persist: true },
            {
                setShowAsText: (_, { showAsText }: { showAsText: boolean }) => showAsText,
            },
        ],
        showAllFrames: [
            false,
            { persist: true },
            {
                setShowAllFrames: (_, { showAllFrames }: { showAllFrames: boolean }) => showAllFrames,
            },
        ],
        showContext: [
            true,
            { persist: true },
            {
                setShowContext: (_, { showContext }: { showContext: boolean }) => showContext,
            },
        ],
    }),

    selectors({
        loading: [() => [(_, props) => props.loading], (loading: boolean) => loading],
        isExpanded: [
            (s) => [s.showDetails, s.loading],
            (showDetails: boolean, loading: boolean) => showDetails && !loading,
        ],
    }),

    listeners(({ actions }) => {
        return {
            setShowContext: () => actions.setShowDetails(true),
            setShowAllFrames: () => actions.setShowDetails(true),
        }
    }),
])
