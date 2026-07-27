---
name: slack-thread-protocol
description: Conventions for replying in Slack — TL;DR first, evidence next, who to tag, when to start a new top-level message. Load before posting any reply.
---

# Skill — slack thread protocol

How to format and route messages so they're useful to humans on-call
and don't add noise.

## Routing rules

- **Always reply in-thread** if you were invoked in a thread (`thread_ts`
  was set on the triggering event).
- **Start a top-level message** only when you're firing on an alert
  webhook and no thread exists yet. The new top-level message is the
  thread root for all subsequent messages of this investigation.
- **Never cross-post.** If the same finding affects multiple channels,
  link from the secondary channel to the canonical thread; don't
  duplicate the body.

## Message shapes

Every message you post should fit one of these shapes. If you're
about to write something that doesn't, stop and reconsider whether
the message is worth sending.

### A. Acknowledgement (Phase 1, optional)

A one-liner posted within seconds of invocation so humans know you're
on it. Use this **only** if you can't react with an emoji
(`@posthog/slack-react`) for some reason.

```text
:eyes: Looking into the `event-ingestion` p99 spike — back in ~2min.
```

### B. Initial alert post (webhook trigger only)

The top-level message when you fire on an alert. One sentence:

```text
:rotating_light: *Alert:* `event-ingestion` p99 latency 4.2s (threshold 1.0s)
since 14:32 UTC — affecting customers in `us-east-1`. Investigating in this
thread.
```

### C. Final hypothesis post

The end-of-investigation summary. Always this shape:

```text
:mag: *TL;DR:* `<one-sentence hypothesis>`. Confidence: <high|medium|low>.

*Evidence*
• <bullet 1 — specific number, timestamp, link>
• <bullet 2>
• <bullet 3>

*Suggested next step*
<one sentence — what should a human do, who should do it>

cc <@USXXXX> if you have a sec — <reason>
```

Keep evidence bullets to 3-5. If you have more, link to a paste /
gist instead of inlining.

### D. "I need more information" post

When you've hit a wall, post this and **stop**. Don't keep digging
in circles.

```text
:warning: I can't make progress without `<specific data>` — it's
outside my reach. Could someone with access to `<system>` share
`<exact thing>`?
```

### E. Resolved-itself post

```text
:white_check_mark: Triggered alert resolved on its own at 14:38 UTC.
Peak `<metric>` was `<value>` (threshold `<value>`); now back to
`<value>`. No further action needed. Closing.
```

## Tagging humans

- **`cc @user`** when you have a specific question for them or your
  hypothesis names them as the most likely owner of the affected
  code.
- **`@here`** **only** if (a) the alert is still firing, (b) blast
  radius is "many customers", and (c) no human has responded in the
  thread yet. Otherwise it's noise.
- **`@channel`** — never. That's a human's call, not yours.

## Don'ts

- Don't reply more than 3 times to the same thread within 5 minutes
  unless a human asked a follow-up. You become noise after that.
- Don't paste log snippets longer than ~15 lines inline. Paste to a
  gist / pastebin (via `@posthog/http-request` if you have a target) or
  describe + link.
- Don't apologise for being unsure. Stating uncertainty clearly is
  high-value; padding it with "sorry" wastes bytes.
