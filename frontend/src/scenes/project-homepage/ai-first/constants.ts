import type { MaxLogicProps } from 'scenes/max/maxLogic'

export const HOMEPAGE_TAB_ID = 'homepage-ai'

// Storage key for the homepage's idle-mode search/AI input draft in tabUiStateLogic.chatDraftsByTab.
// Intentionally distinct from HOMEPAGE_TAB_ID so the homepage Max chat draft (keyed by
// HOMEPAGE_TAB_ID) doesn't collide with the idle-input draft.
export const HOMEPAGE_IDLE_DRAFT_KEY = 'homepage-ai:idle'

// The homepage chat stays inline (rendered by HomepageThread), so it must opt out of maxLogic's
// URL sync like other embedded chats do — otherwise minting a conversation navigates the browser
// to /ai?chat=<id>, mounting a second maxLogic instance that fetches that id before the backend
// row exists.
export const HOMEPAGE_MAX_LOGIC_PROPS: MaxLogicProps = { panelId: HOMEPAGE_TAB_ID, syncUrl: false }
