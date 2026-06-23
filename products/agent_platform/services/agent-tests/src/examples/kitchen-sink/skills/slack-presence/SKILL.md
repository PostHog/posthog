---
description: Conventions for being a good citizen in Slack — TL;DR-first replies, threading vs new top-level posts, mrkdwn quirks, when to react with an emoji vs reply, and editing a 'working…' message in place. Load before any slack-post-message / slack-react, and when a Slack thread resumes.
---

# Slack presence

Slack is a room full of people, not a terminal. Be the colleague who's
helpful and brief, not the bot that floods the channel.

## Reply shape — TL;DR first

People read Slack on their phone, in a hurry. Front-load the answer:

```text
*TL;DR:* events ingestion is healthy — error rate 0.2%, no spike.

Detail: pulled the last 24h of `$exception` events; 0.2% of sessions,
flat vs the 7-day baseline. Nothing in the error-tracking top issues
looks new. :white_check_mark:
```

The first line should stand alone. Everything after is for the person
who wants to dig in.

## Thread, don't broadcast

- **Reply in-thread** to the message that triggered you
  (`thread_ts`). The thread auto-resumes, so a back-and-forth all lands
  in one session — keep it there.
- **Start a new top-level message** only when you're posting something
  genuinely new and channel-wide (the daily delight, a digest). Not for
  a reply.
- **DMs** have no thread; one rolling conversation per person.

## React when a word would be noise

`@posthog/slack-react` is your lightest touch. Use an emoji instead of a
message when:

- You're acknowledging "got it, working on it" → `:eyes:` (the ingress
  may have already added this).
- You finished a side-effect the user asked for → `:white_check_mark:`
  / `:tada:`.
- You're agreeing/closing the loop and a sentence would just be clutter.

Don't react _and_ post the same sentiment.

## Edit, don't spam

For work that takes a few beats, post one "on it…" message and then
**`@posthog/slack-update-message`** to replace it with the result, so the
channel sees one tidy message evolve rather than three. Great for
"searching… → here's what I found."

## mrkdwn is not markdown

Slack's flavour:

- `*bold*` (single asterisks), `_italic_`, `~strike~`, `` `code` ``.
- `<https://url|label>` for links — **not** `[label](url)`.
- `<@U0123>` mentions a user; `<#C0123>` a channel. If a user wrote
  `@jane`, echo their literal text — don't try to resolve it.
- No tables, no headings. Use `•` bullets and short lines.

## Reading context

- `@posthog/slack-read-thread` — pull the whole thread when a request
  spans several messages or refers to "that thing above."
- `@posthog/slack-read-channel` — rarely; for surrounding context a
  thread read won't give you.

Read only what you need — these pull other people's words into your
context, so don't hoover up a channel "just in case."

## Who can drive the thread

This agent is `mention_only` + `auto_resume_threads`, and
`allow_workspace_participants` is **off** — so only the person who
opened the thread advances it. If a _different_ user replies, the
platform records it as an elevation request rather than letting them
steer; you'll keep talking to the original owner. Don't try to route
around that.
