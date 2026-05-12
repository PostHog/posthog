import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import type { watchThisAnswerModalLogicType } from './watchThisAnswerModalLogicType'

export interface WatchThisAnswerPrefill {
    conversationId: string
    humanMessageId: string
    visualizationMessageId: string
    title: string
}

export const watchThisAnswerModalLogic = kea<watchThisAnswerModalLogicType>([
    path(['scenes', 'max', 'watched', 'watchThisAnswerModalLogic']),
    actions({
        openModal: (prefill: WatchThisAnswerPrefill) => ({ prefill }),
        closeModal: true,
        setKnownRepositories: (repos: string[]) => ({ repos }),
    }),
    reducers({
        prefill: [
            null as WatchThisAnswerPrefill | null,
            {
                openModal: (_, { prefill }) => prefill,
                closeModal: () => null,
            },
        ],
        knownRepositories: [
            [] as string[],
            {
                setKnownRepositories: (_, { repos }) => repos,
            },
        ],
    }),
    selectors({
        isOpen: [(s) => [s.prefill], (prefill): boolean => prefill !== null],
    }),
    listeners(() => ({})),
])
