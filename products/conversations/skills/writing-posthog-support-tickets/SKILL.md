---
name: writing-posthog-support-tickets
description: >
  Prepare the content of a support ticket to PostHog so an engineer can act on it
  without a follow-up question. Use when you are about to write a ticket, a bug
  report or a support message to PostHog for the person you are helping, and when
  they ask you to report a problem to PostHog or to write it up for them. Resolves
  the experiment, flag, insight, dashboard, error or replay they are asking about
  to a real link through the PostHog MCP tools, instead of describing it. Then
  writes the ticket in six short parts: what they want, why, what they tried, what
  blocks them, the links, and the exact error. Replaces a pasted debugging
  transcript with a short, specific report, and redacts credentials that hide in
  quoted error text.
---

# Writing a support ticket to PostHog

A support engineer reads the ticket before the thread.
When the ticket names the object, the error and the steps already taken, they can start work.
When it is a transcript of your debugging session, their first reply asks for the URL, and the person waits for another round trip.

Your advantage over the person you are helping is that you reach their project through the PostHog MCP tools.
Use it. Resolve what they are asking about instead of describing it.

This skill covers what goes in the ticket.
The person decides whether to contact support, and the person sends the ticket.

## Step 1: gather before you write

Find the object they mean and take its real link.

| What they mention        | Tool to resolve it                                           | What to take                      |
| ------------------------ | ------------------------------------------------------------ | --------------------------------- |
| An experiment            | `experiment-get-by-flag-key`                                 | Link, id, status                  |
| An experiment's results  | `experiment-metrics-recalculation-latest-retrieve`           | The current metric results        |
| A feature flag           | `feature-flag-get-definition-by-key`, `feature-flag-get-all` | Link, key, whether it is enabled  |
| An insight or a chart    | `insight-get`, `insights-list`                               | Link, short id                    |
| A dashboard              | `dashboard-get`                                              | Link, id                          |
| An error or an exception | The error tracking issue tools in your tool list             | Link, issue id, the exact message |
| A session or a replay    | The session recording tools in your tool list                | Link, session id                  |
| A documented behavior    | `docs-search`                                                | The page you already checked      |

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

## Step 2: write it in six parts

The lengths below come from a sample of real PostHog support tickets.
A ticket that stays inside them reads in one screen, beside the thread.

1. **What they want.** One or two sentences, under 400 characters.
2. **Why they want it.** One sentence, and only when the ask does not explain itself. Leave it out rather than invent a business reason.
3. **What they tried.** Up to five bullets, each under 160 characters. Only steps that changed something or ruled something out.
4. **Why this needs support.** What nobody can see or change from outside the account. Agents skip this part, and it is the part that decides who picks the ticket up.
5. **Links.** Up to five. The object, the replay, the screenshot.
6. **The error, quoted exactly.** Under 600 characters: the message and the top frames. Not a paraphrase of it.

Use this shape:

```markdown
**What I want:** <one or two sentences>

**Why:** <one sentence, or omit>

**What I tried:**

- <step, and what it showed>
- <step, and what it showed>

**Why this needs support:** <what I cannot see or change from outside>

**Links:**

- Experiment: <url>
- Replay: <url>

**Error:**

<exact text, top frames only>
```

Write it in the person's voice, because they are the one who sends it.
Leave out any part you have nothing real to put in.
An empty heading is worse than a missing one.

## Step 3: cut it down

A long ticket is the most common fault in one an agent writes.
Cut these before you hand it over:

- The transcript of what you did. Keep what a step showed, drop the narration.
- Your hypotheses written as findings. Either mark them ("the flag may evaluate before identify runs") or cut them.
- The same point made twice in different words.
- Greetings, apologies and sign-offs.
- Whole event payloads and full stack traces. The top frames carry the information.
- Code written during the session, unless it reproduces the problem on its own.

A good ticket is usually under 200 words, plus the error block.

## Never put these in a ticket

- Credentials of any kind: personal API keys, `phx_` and `phs_` tokens, cookies, session tokens, auth headers, database passwords.
- Another customer's data.
- A full user record. One distinct id, or one person link, is enough.

A credential often hides inside the error text you are quoting.
Read the quote before you paste it.
When you replace something, say that you replaced it, so nobody hunts for a token that is not there.

## Step 4: hand it over

The person sends the ticket, not you.
Never say that a ticket was filed.

When your tool list holds a PostHog support draft tool, save the ticket as a draft and give them the review link it returns.
Otherwise give them the finished text and ask them to send it from the in-app support form, which attaches their project and recent session for them.
When they are not in the app, point them at https://posthog.com/support.

Say which links you could not resolve, so they can fill those in before they send it.

## Before you hand it over, check

- Every link came from a tool result, not from a guess at PostHog's URL shape.
- The error is quoted, not summarized.
- "Why this needs support" says something the engineer cannot work out alone.
- No credential survived the quoting.
- It reads in one screen.
