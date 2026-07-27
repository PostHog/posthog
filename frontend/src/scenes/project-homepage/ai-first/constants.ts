export const HOMEPAGE_TAB_ID = 'homepage-ai'

// Storage key for the homepage's idle-mode search/AI input draft in tabUiStateLogic.chatDraftsByTab.
// Intentionally distinct from HOMEPAGE_TAB_ID so the homepage Max chat draft (keyed by
// HOMEPAGE_TAB_ID) doesn't collide with the idle-input draft.
export const HOMEPAGE_IDLE_DRAFT_KEY = 'homepage-ai:idle'
