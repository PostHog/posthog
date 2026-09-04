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

## Shared edits

The client reads all missing operations before it accepts a new board snapshot.
It keeps stream operations received during the initial read. A failed initial
read retries the board snapshot, not only the operation log. A live connection
keeps polling while operations are missing, then stops after recovery.
It keeps each submitted operation unchanged until the server confirms it.
New edits use new operation IDs, including after a failed response.
When the server reports `server_snapshots`, saves send operations without a full
board snapshot. This includes moves and size changes. Older servers keep the
existing client checkpoint path. Layout changes update board previews at once.
When a full restore is present, the fold starts there. Earlier operations stay
in history but do not need to run again to produce the current board.

Undo removes the user's last edit and keeps unrelated later edits from other users.
Undo requires a known user identity. The board loads that identity through the
existing authenticated client and applies it to new edits when it arrives.
Each board owns its state subscription. Updates from a closed board do not
render the next board.
The code editor keeps an open draft when another user changes the fragment.
Board lists are cleared when the user changes accounts or projects.
Board deletion uses the existing eight-second Undo window. Undo cancels the
request before the server receives it. The Undo notice closes when deletion starts,
even if the notice has keyboard focus.

The local board cache stores synced data, including name changes. It waits for
missing operations before it writes a new head. An unchanged poll or repeated
stream event does not rebuild the snapshot or write the cache file.
The workspace server writes one cache file at a time per board. While a write
is active, it keeps only the latest queued snapshot. Different boards can write
in parallel. Cache files use compact JSON, and failed writes remove their
temporary files.

The server checks operation and snapshot fields before it stores them.
An open board stream checks access before it sends each group of events.
The stream closes if the board is deleted or moves to a space the user cannot read.

The server uses a bulk insert for operation batches. A retry with no new
operations does not update the board row. Each board uses its existing row lock
to sequence edits. The log and current records change in the same transaction.
The server applies operations to fragment and shared-state records. A normal
move reads and writes only the affected fragment metadata, not source or state.
The first write to an old board converts its saved snapshot and later operations.
The old snapshot and history remain available. Normal saves do not read them.
Board-list queries project the fragment count and the first 24 preview boxes in
Postgres. They do not transfer fragment code or shared state into Django.

Source text is immutable and addressed by its SHA-256 hash within a board.
Fragments and new history records use source references. The API resolves these
references for older clients. New desktop clients request `compact=true` and
receive each active source version once. Board reads select the record values
and their sequence in one database query, so concurrent writes cannot mix them.

The frame has a bounded compile cache for identical source. The cache holds at
most 2,097,152 characters of source and output. Modules remain separate for
each fragment, so their module state is not shared. Custom code still runs while
its fragment is outside the visible area; this change does not suspend effects.

Cursor coordinates are rounded to world units. Presence uses one request at a
time and sends at most ten requests per second, including selection and caret
changes. While a request is active, only the latest pending presence is kept.
Presence does not include fragment code or shared state and is not saved in the
board log. Closing or switching boards cancels queued presence work.

A restore sends its snapshot once and uses the normal request size limit.
Redis keeps a reload marker for an operation larger than 64 KB. Clients use the
existing database log to read that operation. The full restore is kept in history.
The desktop does not retry operations that the server rejects as invalid input.

## What stays open

- **Name resolution.** A page can make the browser resolve a name, and a name
  carries a few bytes. The document turns prefetching off and removes `<link>`
  elements, and the session proxy resolves names at the proxy, which is dead.
- **The agent.** Board text reaches an agent that can write files and run
  commands. The prompt says board content is data, and the board text cannot
  spell the prompt's own markers. That lowers the risk. The boundary is the
  capability set of the session that reads board content, not the wording.
