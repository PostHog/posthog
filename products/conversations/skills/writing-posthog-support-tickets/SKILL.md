---
name: writing-posthog-support-tickets
description: >
  Writes a support ticket to PostHog's support team for the person you are helping,
  so the engineer who picks it up can act on it without a follow-up question. Use when
  you cannot solve a person's PostHog problem and they want a human to look, when they
  ask to contact PostHog support, raise a ticket, or write a problem up for PostHog,
  and when PostHog AI hands a conversation over to support. Resolves the flag,
  experiment, insight, dashboard, error or replay to a real link through the PostHog
  MCP tools instead of describing it, then writes a short ticket the person sends:
  what they want, their questions, what they tried, what the assistant checked, what
  is left for support, links, details and the exact error. Keeps the person's steps
  apart from the assistant's, leaves the assistant's replies out, and removes
  credentials from quoted error text.
---

# Writing a support ticket to PostHog

A support engineer reads the ticket before the thread.
When the ticket links the object, quotes the question and the error, and says what was already ruled out, they can start work.
When it carries a debugging transcript or the assistant's replies, the question is buried, and their first reply asks for it again.

You reach the person's project through the PostHog MCP tools, and they usually cannot.
Use that to resolve what they are asking about instead of describing it.

You write the ticket.
The person decides to contact support, and the person sends it.

## When to offer a ticket

Offer a ticket when one of these is true:

- They ask for a human, for PostHog support, or for a ticket.
- The answer needs something only PostHog can see or change, such as billing, their account, or processing on PostHog's side.
- You confirmed a reproducible error and cannot explain it.
- They disagree with your answer and want PostHog to look.

Search the docs with `docs-search` first if you have not.
Your own conclusion that something is a PostHog bug is not a reason on its own.
Tell them what you found, offer the ticket, and write it once they say yes.

Opening a ticket needs a paid plan or a trial, except for a billing question.
If they are on the free plan, say so before you write one.

## Step 1: gather before you write

Find the object they mean and take its real link.

| What they mention        | Tool to resolve it                                             | What to take                      |
| ------------------------ | -------------------------------------------------------------- | --------------------------------- |
| An experiment            | `experiment-get-by-flag-key`                                   | Link, id, status                  |
| An experiment's results  | `experiment-metrics-recalculation-latest-retrieve`             | The current metric results        |
| A feature flag           | `feature-flag-get-definition-by-key`, `feature-flag-get-all`   | Link, key, whether it is enabled  |
| An insight or a chart    | `insight-get`, `insights-list`                                 | Link, short id                    |
| A dashboard              | `dashboard-get`                                                | Link, id                          |
| An error or an exception | The error tracking issue tools in your tool list               | Link, issue id, the exact message |
| A session or a replay    | The session recording tools in your tool list                  | Link, session id                  |
| Their SDK and version    | The query tools in your tool list, on a recent event they sent | `$lib` and `$lib_version`         |
| A documented behavior    | `docs-search`                                                  | The page you already checked      |

A 404 from the results tool means the experiment has no results yet.
Put that in the ticket, because it is often the thing the person is asking about.

Take every link to a project object from the `_posthogUrl` field of the tool result.
Never build a PostHog URL by hand.
The region and the project id differ for every account, and a wrong link reads as a real one.

`docs-search` is the exception. It returns a `content` string of titles, URLs and excerpts, and no `_posthogUrl`, so copy a documentation URL out of that content as it stands.

Tool names change a little between MCP versions.
When a name above is not in your tool list, use the one that matches the object type.

When a lookup finds nothing, or fails, write that in the ticket.
"No experiment matches flag `checkout-v2`" is a useful fact.
An invented link costs a round trip and loses the engineer's trust in the rest of the ticket.

Ask the person only for what is missing and matters, such as the exact error text, whether it keeps happening, and what they expected.

## Step 2: write it

Every part below except the first is optional.
Leave out any part you have nothing real for.
An empty heading is worse than a missing one.

1. **What I want.** One or two sentences, under 400 characters. Name the product, the feature or the page, and what goes wrong. The error goes in its own part.
2. **Why.** One sentence, only when they said why. Never invent a reason.
3. **Questions.** Each question they asked, one line each, up to six, in their own words. Trim a question, but do not reword it.
4. **What I tried.** Only the steps the person took. Up to five bullets, each under 160 characters, with what each one showed.
5. **What PostHog AI checked.** The checks you ran through the tools, and what each one showed or ruled out. Up to five bullets. Use your own name in place of PostHog AI, such as Claude Code or Codex.
6. **PostHog AI told me.** One sentence, only when you gave an answer that did not work or that they disagree with. It is the answer they were given, not a confirmed fact.
7. **Left for support.** The first thing you could not determine, and what only someone at PostHog can see or change to settle it. One or two sentences.
8. **Links.** Up to five, one per line, each starting with what it is: Dashboard, Experiment, Feature flag, Insight, Project, Replay, Survey, Error, or Docs.
9. **Details.** Up to five facts the engineer needs, such as SDK and version, platform, region, when it started, how many users it affects, and any id that has no link. Copy identifiers exactly.
10. **Error.** The message and the top frames, copied exactly, under 600 characters.

Keep the person's steps apart from yours.
The engineer needs to know which steps happened in the person's app and which ones you ran through the tools.

Use this shape:

```markdown
**What I want:** <one or two sentences>

**Why:** <one sentence>

**Questions:**

- <question, in my words>

**What I tried:**

- <step, and what it showed>

**What PostHog AI checked:**

- <check, and what it showed>

**PostHog AI told me:** <one sentence>

**Left for support:** <the first thing nobody could determine from outside>

**Links:**

- Feature flag: <url>
- Replay: <url>

**Details:**

- <fact>

**Error:**

<exact text, top frames only>
```

Write it in the person's voice, because they send it.
Stay under 250 words, plus the error.

## Step 3: cut it down

A long ticket is the most common fault in one an agent writes.
Cut these before you hand it over:

- The transcript of what you did. Keep what each check showed, and drop the narration.
- Your own replies from the conversation. "PostHog AI told me" carries one sentence of them, and nothing else does.
- Hypotheses written as findings. Mark one as a guess ("the flag may evaluate before identify runs") or cut it.
- The same point made twice in different words, such as a check repeated in "Left for support".
- Greetings, apologies and sign-offs.
- Whole event payloads and full stack traces. The top frames carry the information.
- Code written during the session, unless it reproduces the problem on its own.

## Never put these in a ticket

- Credentials of any kind: personal API keys, `phx_` and `phs_` tokens, cookies, session tokens, auth headers, database passwords.
- Personal data of their users, such as email addresses or names. One distinct id, or one person link, is enough.
- Another customer's data.

A credential often hides inside the error text you quote.
Read the quote before you paste it.
When you replace something, say that you replaced it, so nobody hunts for a token that is not there.

## Step 4: hand it over

Show the person the full ticket.
Tell them nothing is sent until they send it, and never say that a ticket was filed.
Do not promise a response time.

Then tell them where to send it:

- **In PostHog AI:** they type `/ticket` in this conversation. It opens the support form linked to the conversation, and they paste the ticket into the message.
- **Elsewhere in the PostHog app:** the support form, which attaches their project and recent session.
- **Outside the app:** https://posthog.com/support.

Do not write a link to the conversation into the ticket.
`/ticket` attaches it in PostHog AI, and support cannot open a conversation from any other assistant.

Say which links you could not resolve, so they can add those before they send it.

## Before you hand it over, check

- Every link came from a tool result, or was copied from `docs-search` content.
- The questions are in the person's own words.
- "What I tried" holds only the person's own steps.
- Your replies are not in it, apart from one sentence in "PostHog AI told me".
- "Left for support" names one thing, and says what only PostHog can see or change.
- The error is quoted, not summarized, and no credential survived the quoting.
- It reads in one screen.
