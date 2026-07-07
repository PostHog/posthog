---
description: How to read a kudos out of a message — pull the recipient handle(s), the praise, and themes; decide when to ask ONE clarifying question vs record straight away. Load at the start of every capture.
---

# Capturing a kudos

A kudos has exactly two things that matter: **who it's for** and
**what they did**. Everything else (themes, the giver, the link) is
metadata you can derive. Your job here is to extract those two things,
or notice that one is missing and ask for it.

## Pull these fields

| Field              | From                                                                                              |
| ------------------ | ------------------------------------------------------------------------------------------------- |
| `recipient_handle` | The `@handle` / `<@U…>` the praise is aimed at. **Required.**                                     |
| `message`          | The praise itself, cleaned of the @bot mention and filler. Required.                              |
| `giver_handle`     | Who sent the message — `user:` in the `[slack]` envelope, or the chat principal.                  |
| `themes`           | 0–3 lowercase tags you infer (`teamwork`, `shipping`, `mentoring`, `above-and-beyond`). Optional. |

Store handles **verbatim** — don't normalise `<@U0123>` to a name,
don't strip a `.` out of `@ben.white`. The handle is the key.

## Multiple recipients

"kudos to @jane and @raj for the launch" → **two rows**, same praise
text, one per recipient. They share nothing in the store but the
`message`; each gets its own `kudos_id` (see `kudos-storage`).

## When to ask vs record

Ask **one** clarifying question, in-thread, only when a required field
is genuinely missing:

- **No recipient** ("big kudos for today's deploy!") → "Nice — who's
  this for?"
- **No praise** ("kudos to @jane") → "Love it — what did @jane do?"

Then **stop and wait**. The thread resumes this session when they
reply. Do not stack questions, and do not ask about optional fields
(themes, links) — infer or skip those.

Record straight away (no question) when both required fields are
present, even if terse. "kudos @raj solid review" is recordable:
recipient `@raj`, message "solid review".

## What is NOT a kudos

Don't write a row for:

- A question to the bot ("@kudos-bot how many did I give?").
- General thread chatter where you were auto-resumed but not
  addressed (the seed message is flagged `mention: false`).
- A request to retract or edit — handle that explicitly, don't append.

When in doubt and it reads like appreciation, lean toward capturing —
a missing-recipient question is cheap; a lost kudos is the failure
mode this bot exists to prevent.
