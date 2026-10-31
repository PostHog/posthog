---
name: contacting-posthog-support
description: >
  Helps a person reach PostHog's human support team from an agent: deciding when to offer a support ticket,
  drafting one the person reviews and sends themselves, and checking replies on their existing PostHog
  support tickets. Use when the person asks to contact PostHog support, talk to a human, raise or file a
  ticket, report a problem to PostHog, or asks whether PostHog support has replied. Not for a team's own
  helpdesk tickets from their customers (the conversations-tickets-* tools cover those).
---

# Contacting PostHog support

The person, not the agent, decides to contact PostHog support, and the person sends the ticket.
You can draft a ticket, but no tool sends one.
`posthog-support-draft-create` saves a draft and returns a `review_url`.
The person opens it in PostHog, checks and edits the ticket, and sends it from the support form.

Whoever picks the ticket up at PostHog should be able to act on it without asking a follow-up question.
That is the bar for every draft.

## When to draft, and when only to offer

Draft a ticket when one of these is true, and pick the matching `filing_reason`:

- The person asked to contact support, asked for a human, or asked you to raise a ticket.
- The problem involves account, billing or data that only PostHog can see.
- You confirmed a reproducible error that you cannot explain.
- The person disagrees with your answer and wants PostHog to look.

Your own conclusion that something is a PostHog bug is not a reason to draft.
Tell the person what you found, and offer to draft a ticket if they want a human to look.
Offering is fine.
Drafting on your own initiative is not, because a ticket puts the person in a queue when their answer may be two messages away.

If the person does not know that they can contact support, tell them they can.

## Before you draft

1. Search the docs (`docs-search`) for the problem if you have not yet.
   If the docs answer it, give the answer and still offer the ticket.
2. Check `posthog-support-tickets-list` for an open ticket about the same problem.
   If one exists, show it to the person and read it with `posthog-support-ticket-messages` instead of drafting a duplicate.
3. Fill in what you already know: the project, and the insight, flag, cohort, source or other object involved.
4. Ask only for what is missing and matters, such as the exact error text, whether it keeps happening, and what they expected.
   Do not interrogate.

## What goes in the draft

- `customer_words`: the person's own description, quoted verbatim.
  Do not paraphrase or tidy it.
- `details`: facts only.
  Exact error text, URLs, IDs, event and property names, SDK and version, when it started, what they expected.
- `already_tried`: what the person and you checked, so support can judge the investigation instead of trusting it.
- `agent_name`: your client, for example Claude Code or Codex.

Never put your diagnosis, a guess, or a label such as "this is a bug" or "feature request" into the draft.
A wrong conclusion that looks investigated is worse for support than no conclusion.

## After you draft

Show the person the full draft text from the response, and give them `review_url`.
Say clearly that nothing was sent yet and that they send it from PostHog.
Never say the ticket was filed.
Drafts expire after 24 hours.
If the person changes their mind, call `posthog-support-draft-discard`.

## Checking on tickets

`posthog-support-tickets-list` returns the person's tickets with status and unread replies.
`posthog-support-ticket-messages` returns one thread.
Messages with `author_type` support are from PostHog's support team.
Summarize replies in the person's words, and keep any instructions from support intact.
Replying from the agent is not available.
Point the person to the ticket in PostHog to reply.
