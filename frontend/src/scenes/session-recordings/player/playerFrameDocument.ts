// rrweb builds its replay iframe on about:blank, and a frame on a local scheme (about:blank,
// about:srcdoc) inherits its embedder's whole policy, report-uri included. Mounting recorded content
// inside this document instead puts it in the inheritance chain, so a recorded page is judged against
// its policy rather than the app's. CSPMiddleware supplies it.
export const PLAYER_FRAME_SRC = '/replay_player_frame/index.html'
export const PLAYER_FRAME_CONTENT_ID = 'player-frame-content'
