# The Canvases v2 board sandbox

A fragment is code somebody else wrote. An agent writes most of them, from data
it read, and everyone on a shared board can change them. The app therefore
treats fragment code as untrusted, and runs it where it can do no harm.

## Where a fragment runs

The desktop app serves the board document on `posthog-canvas://board/` and shows
it in a `<webview>` with its own `canvas-board` partition. That gives the board:

- **its own process**, so a fragment that loops forever freezes its own board and
  not the application. The host watches the `unresponsive` event and offers to
  stop the board.
- **its own session**, which carries a dead proxy, a permission handler that
  refuses everything, a download block, and a request rule that cancels every
  HTTP, HTTPS and WebSocket request the board makes.
- **a real origin**, so the content policy arrives as a response header.

The board reaches PostHog only over the message bridge: the frame asks, the host
decides, the host answers. The frame never holds a token.

## The layers, strongest first

1. **The session and the request rule.** Page code cannot reach either.
2. **Vendored modules.** `scripts/fetch-canvas-modules.mjs` downloads the
   fragment libraries once, checks every byte against `canvas-modules.lock.json`,
   and the app serves them from disk. No content delivery network is trusted at
   run time, and a package that goes bad upstream cannot change what people run.
3. **The content policy.** The browser applies it. It closes fetch, images,
   media, forms, frames and `eval`. It does not govern name resolution or WebRTC,
   so the frame also drops the WebRTC constructors and removes any `<link>` a
   fragment inserts.
4. **The import guard and the write guard.** These stop mistakes, and stop an
   agent from writing code that loads something unreviewed. They are not a
   boundary: `blob:` must stay in `script-src` for a fragment to mount at all, so
   a determined fragment can still build code at run time. Do not count them
   twice.

## The trust decision

**One board is one trust domain.** Every fragment of a board shares one realm.
Fragment A can read fragment B's document, replace React under it, and take the
results of B's queries.

This is accepted, because everyone who can edit a board can already run code on
it. It is written down because it is not obvious: an agent writes fragments from
data it read, so the authors of two fragments on one board can differ in
practice. The alternative is one frame per fragment, which costs a process per
fragment. Revisit this if a board ever shows a fragment its viewer cannot edit.

## What a board may spend

A fragment runs on its own as soon as the board opens, so its appetite is
bounded: 8 reads at a time, more are queued, at most 120 in a burst and 3 a
second after that; shared-state writes get their own allowance. A person's board
never meets these numbers. A loop meets them at once.

## What stays open

- **Name resolution.** A page can make the browser resolve a name, and a name
  carries a few bytes. The document turns prefetching off and removes `<link>`
  elements, and the session proxy resolves names at the proxy, which is dead.
- **The agent.** Board text reaches an agent that can write files and run
  commands. The prompt says board content is data, and the board text cannot
  spell the prompt's own markers. That lowers the risk. The boundary is the
  capability set of the session that reads board content, not the wording.
