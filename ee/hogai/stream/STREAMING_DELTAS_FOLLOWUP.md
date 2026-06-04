# Follow-up: stream token deltas instead of full accumulated messages

Status: **proposal / not implemented.** This is the larger, breaking half of the
event-loop-starvation work. The first PR offloaded per-chunk (de)serialization off the ASGI
event loop (gated by `MAX_AI_STREAM_OFFLOAD_SERIALIZATION`). That buys headroom but does **not**
remove the underlying O(n²) growth — this writeup does. It needs a frontend contract change, so
it ships separately.

## The problem: O(n²) per streamed message

While an assistant message streams token-by-token, the chunk processor re-emits the **entire
accumulated message every token**:

`ee/hogai/chat_agent/stream_processor.py:276-282`

```python
# Merge message chunks
self._chunks[run_id] = merge_message_chunk(self._chunks[run_id], message)
# normalize_ai_message() returns a list when server_tool_use blocks are present,
# but we only stream the latest message for incremental updates
messages = normalize_ai_message(self._chunks[run_id])
return [messages[-1]] if messages else None
```

`self._chunks[run_id]` is the full accumulated message; `messages[-1]` is therefore the whole
message so far, re-sent on every token. Each of those whole-message chunks then flows through:

- **write side** (Temporal worker → Redis): `ConversationStreamSerializer.dumps` → `pickle.dumps`
  + `xadd` (`redis_stream.py`), once per token;
- **read side** (Redis → client, on the web ASGI loop): `pickle.loads`
  (`ConversationStreamSerializer.deserialize`, called from `read_stream`) then `model_dump_json`
  (`sse.py`), once per token, yielded per chunk in `ee/api/conversation.py` `async_stream`.

For an `n`-token message, token *k* serializes a payload of size O(*k*), so the total work is
`Σ O(k) = O(n²)` in both CPU and Redis bytes — on **both** the write and read loops. With the
observed heavy output-token tail (messages up to ~23.7k tokens), the per-message cost on the
shared serving loop is what starves the dependency-free `/_livez` probe and triggers the
liveness-kill flap.

Offloading (PR 1) moves that cost to a thread pool so the loop keeps answering probes, but the
total work is unchanged. Deltas reduce it from O(n²) to **O(n)**.

## The fix: emit only the new content per chunk

Instead of `messages[-1]` (full accumulated), emit the **delta** since the previous chunk for
that `run_id` — the newly-appended text content (and incremental tool-call args). The client
accumulates deltas into the in-progress message keyed by message `id`.

Sketch (server, `_handle_message_stream`):

- keep the existing `merge_message_chunk` accumulation (still needed for the authoritative
  end-of-node message);
- additionally track the last-emitted length/state per `run_id`;
- emit a delta event carrying `{id, content_delta, tool_call_args_delta, index}` rather than the
  full message.

The **final** persisted message (real `id`, dispatched at node end via `_handle_node_end` →
`process(MessageAction(...))`) should keep being sent **in full** — it is the authoritative state
and the correctness backstop. Only the ephemeral in-progress (temp-`id`) stream becomes deltas.

## Why it's a separate, breaking PR

### 1. Frontend contract change (the blocker)

Today the client **replaces** the in-progress message wholesale, keyed by `id`:

`frontend/src/scenes/max/maxThreadLogic.tsx:2091-2097`

```ts
if (existingMessageIndex >= 0) {
    // When streaming a message with an already-present ID, we simply replace it
    actions.replaceMessage(existingMessageIndex, { ...parsedResponse, status: ... })
}
```

With deltas the client must **append** `content_delta` to the existing message's content (and
merge partial `tool_calls` args) instead of replacing. That is a wire-format change shared with
every Max client (web app, and any other SSE consumer). It needs:

- a versioned event shape (e.g. a new `event:` type, or a `delta: true` discriminator on
  `event: message`) so old clients keep working during rollout;
- server + frontend shipped together, ideally behind a flag, with old full-message behavior as
  the fallback until clients are updated.

### 2. Reconnect / resume correctness (the subtle one)

The current full-re-emit design is **self-healing on reconnect and Redis trim**, and that is not
incidental — it's load-bearing. The conversation Redis stream is capped
(`CONVERSATION_STREAM_MAX_LENGTH = 1000`, `xadd maxlen ~approximate`). A reconnecting client
re-reads from `"0"` (`ConversationRedisStream.read_stream`). Because every retained entry is a
**complete snapshot**, even after trimming the latest entry still carries the full message-so-far
— a late joiner is always consistent.

Deltas break that property: a long message (>1000 token-chunks — well within the 23.7k-token
tail) will have its early deltas trimmed, so a client reading from `"0"` would reconstruct only a
**suffix** of the text. A delta design must therefore add one of:

- **periodic snapshots** interleaved into the stream (full state every N tokens), and have
  readers start from the most recent snapshot; or
- **resync on reconnect**: the reconnecting client fetches current state from the checkpoint /
  persisted conversation, then resumes deltas from `"$"` (new messages only); or
- rely on the end-of-node full message to correct, accepting a transient wrong-suffix render
  during the gap (likely not acceptable UX for active reconnects).

This is the bulk of the design work and the main reason it can't ride along with the
mechanical offload change.

### 3. Edge cases to preserve

- `normalize_ai_message` can return **multiple** messages when `server_tool_use` blocks are
  present; the delta scheme must track per-message (per `id`/index) offsets, not a single cursor.
- partial **tool-call args** stream as growing JSON fragments — deltas must concatenate to valid
  JSON only at completion; the client cannot parse mid-stream args.
- **reasoning / thinking** content streams alongside answer content; both need independent delta
  cursors.
- ordering must stay strict (already guaranteed: each chunk is awaited before yield).

## Expected impact

- Per-message serialize/transfer cost: **O(n²) → O(n)** on both the write and read loops, and a
  corresponding drop in Redis bytes and `xadd`/`xread` payload sizes.
- Removes the structural driver of `/_livez` starvation rather than only relocating it
  (complementary to the PR-1 offload, which can then be reserved as a safety valve).

## Sequencing

1. **PR 1 (this one):** offload (de)serialization off the loop behind
   `MAX_AI_STREAM_OFFLOAD_SERIALIZATION`; add timing histograms. Non-breaking, immediate relief.
2. **PR 2 (this writeup):** versioned delta event shape + server delta emission + frontend
   accumulation + reconnect snapshot/resync. Behind a flag, with full-message fallback.
