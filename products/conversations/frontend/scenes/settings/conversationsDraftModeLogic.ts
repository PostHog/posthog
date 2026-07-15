import { actions, kea, path, reducers } from 'kea'

import type { conversationsDraftModeLogicType } from './conversationsDraftModeLogicType'

// Browser-local default for the ticket composer's draft mode. Each ticket seeds its own
// toggle from this on open; flipping the per-ticket toggle does not write back here.
export const conversationsDraftModeLogic = kea<conversationsDraftModeLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'settings', 'conversationsDraftModeLogic']),
    actions({
        setDraftModeDefault: (enabled: boolean) => ({ enabled }),
    }),
    reducers({
        draftModeDefault: [
            false,
            { persist: true, storageKey: 'conversations_draft_mode_default' },
            {
                setDraftModeDefault: (_, { enabled }) => enabled,
            },
        ],
    }),
])
