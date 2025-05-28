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
        setShowAsJson: (showAsJson: boolean) => ({ showAsJson }),
        setShowContext: (showContext: boolean) => ({ showContext }),
        setShowAllFrames: (showAllFrames: boolean) => ({ showAllFrames }),
    }),

    reducers({
        showDetails: [
            true,
            {
                setShowDetails: (_, { showDetails }: { showDetails: boolean }) => showDetails,
            },
        ],
        showAsText: [
            false,
            { persist: true },
            {
                setShowAsJson: (prevState, { showAsJson }: { showAsJson: boolean }) => (showAsJson ? false : prevState),
                setShowAsText: (_, { showAsText }: { showAsText: boolean }) => showAsText,
            },
        ],
        showAsJson: [
            false,
            { persist: true },
            {
                setShowAsText: (prevState, { showAsText }: { showAsText: boolean }) => (showAsText ? false : prevState),
                setShowAsJson: (_, { showAsJson }: { showAsJson: boolean }) => showAsJson,
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
