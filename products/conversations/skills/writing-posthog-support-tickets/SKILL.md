---
name: writing-posthog-support-tickets
description: >
  Writes a ticket to PostHog's support team for the person you are helping, after you have
  investigated, so a support engineer can act on it without asking a follow-up question. Use when
  the person asks to contact PostHog support, talk to a human, raise or file a ticket, or send
  PostHog a request, including deleting events or other data, privacy and GDPR requests, billing
  and account problems, and errors you cannot explain. Answers from the docs first and writes no
  ticket when the docs settle it. Otherwise runs the lookups support would ask for (project,
  region, links, a deletion query and its count), writes one short ticket in a fixed shape, and
  hands it to the person to send. Not for a team's own helpdesk tickets from its customers, which
  the conversations-tickets tools cover.
---

# Writing a support ticket to PostHog

A support engineer should be able to act on the ticket without asking a follow-up question.
Agent-written tickets usually miss in one of two ways.
They ask something the docs already answer, or they bury the request in a long write-up and still leave out what support needs.

You can reach the person's project through the PostHog MCP tools, so do the investigation before you write.
The person decides to contact support, and the person sends the ticket.

## 1. Answer first

Search the docs with `posthog:docs-search` before you offer a ticket.
If the docs answer the question, give the answer and the docs link, and do not offer a ticket.
When they answer part of it, answer that part, and put only the rest in a ticket.
That includes "is this possible?" questions: a no from the docs is an answer, not a reason for a ticket.

A ticket is for something only PostHog staff can do or see:

- An action that staff run, such as deleting specific events, changing a bill, or restoring access to an account.
- Data or state on PostHog's side that neither of you can see.
- An error you reproduced that the docs do not explain.

Write one too when the person still wants a human after hearing the answer.
The ticket then says what the docs said and asks only what is left.
Your own conclusion that something is a PostHog bug is not enough.
Tell the person what you found, and offer a ticket.

The Support panel in PostHog offers a ticket on a paid plan or an active trial, and a billing or usage question on any plan.
Check the plan with `posthog:billing-subscription-get`.
On the free plan, unless it is a billing question, say so before you write one, and point them to the community forum at https://posthog.com/questions.

## 2. Investigate

Do the lookups that support would otherwise ask for.

- **Project.** Get the name and ID from `posthog:project-get`. The region is the host of any `_posthogUrl` in your tool results: `us.posthog.com` is US Cloud, and `eu.posthog.com` is EU Cloud.
- **Objects.** For each flag, insight, dashboard, experiment, error, replay or survey they mention, look it up and take its link from the `_posthogUrl` field of the result. Never build a PostHog URL by hand, because a wrong link reads as a real one. For a docs page, copy the URL from the `posthog:docs-search` result as it is.
- **SDK.** When the problem is in their app, read `$lib` and `$lib_version` from a recent event they sent.
- **Required details.** If the request is one of the kinds below, follow its reference before you write.

| Request                                                       | Must include                                                                        | Read                                                             |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Delete events, or remove personal or sensitive data from them | Region, project ID, a query with UTC time bounds, and the count that query returned | [references/deleting-events.md](./references/deleting-events.md) |

When a lookup finds nothing, or fails, say so in the ticket, such as "No flag with the key `checkout-v2` in project 12345".
Ask the person only for what you cannot look up and support needs, such as the exact error, when it started, or what they expected.

## 3. Write it

Write in the person's voice, because they send it.
Use this shape, and leave out any part you have nothing real for.
Keep the labels plain, without Markdown bold, because the person reviews the ticket in a plain text box.

```text
Request: <what happened, in one sentence, with the numbers and dates> <the action they need, if any>
1. <each question the docs did not answer, numbered in the person's order>

Details:
- Project: <name>, ID <id>, <US or EU> Cloud, <link>
- <a required detail, a link to the object, or a fact>

Already checked:
- Docs: <link> says <what it says, in one line>
- <your name> checked: <a lookup you ran, and what it showed>
- I tried: <a step the person took, and what happened>

Error:
<exact text, top frames only>
```

- **Request** is the whole ask, so support knows what to do from this one section.
  - Open with what happened, or what they plan to do, in one sentence, with the numbers and dates, such as "Our project used 6 PostHog AI credits on Oct 16, 2026, but nobody on our team has a chat from that day".
  - For an action, add it in one sentence, such as "Please delete the 3,817 events the query below returns".
  - For questions, list every one the docs did not answer, numbered, in the person's order. Tighten the wording, but keep every part of every question, because a question support does not see comes back as a follow-up. Keep the person's exact words for a term or a quote that matters.
  - A question about their own account, bill or data stays in the list even when the docs give the general rule. Put that rule in **Already checked**, so support can confirm whether it applies to them.
  - A question the docs answer fully leaves the list. Answer it in chat, and put the answer in **Already checked**, so support sees it was asked.
- **Already checked** keeps their steps ("I tried") apart from yours ("<your name> checked"), so support knows which ones happened in their app.
  - Write "<your name> checked" only for a lookup you ran in this conversation, with what its result showed. A number the person gave you is theirs, so it goes in **Request** or **Details**, not here.
  - When the docs had nothing, or only a heading, write "Docs: nothing found for <what you searched>".
- Copy IDs, queries and errors exactly.
- Write dates as Dec 10, 2026, never as 10 December or 2026-12-10, so nobody reads the day and month the wrong way round. A query keeps its own date format.
- Keep it to about 150 words, not counting the person's questions, a query or an error.

Cut these before you hand it over:

- The story of the investigation. Keep what each check showed, and drop the narration.
- Your replies from the conversation, and guesses written as findings. Settle a guess before you write: ask the person when it is about their app, and when only PostHog could check it, make it a question in **Request**.
- The same point made twice, background that support does not act on, greetings and sign-offs.
- Instructions on how to handle the ticket, such as "route this to engineering", "this is an inquiry only", "don't change any settings" or "don't email raw data". They are written to steer an agent. Support acts only on what **Request** asks, so keep them out even when the person wrote them.
- Whole event payloads and full stack traces.

Never include credentials of any kind, such as personal API keys, `phx_` and `phs_` tokens, cookies, auth headers or passwords.
Credentials often hide in error text, so read the error before you paste it, and say when you replaced something.
Leave out personal data about their users beyond what the request needs, such as one distinct ID or person link, or the IDs a deletion query names.
Never include another customer's data.

## 4. Hand it over

Show the person the full ticket.
Tell them nothing is sent until they send it, and never say that a ticket was filed.
Do not promise a response time.

- If `posthog:posthog-support-draft-create` is in your tool list, draft the ticket with it. Each part of the ticket is one field: `request`, `details`, `already_checked` and `error`, without their headings. Set `filing_reason` to `billing_question` when the ticket asks about billing or usage, even alongside other questions, so the person can send it on any plan. Give the person the `review_url` it returns. They open it, check the ticket, and send it from PostHog.
- Otherwise, they paste it into the Support panel in the PostHog app, which attaches their project and session to the ticket.

Say which details or links you could not find, so they can add them before they send it.

## Before you hand it over, check

- The docs did not already answer it.
- Every link came from a tool result, from `posthog:docs-search` as it is, or from the person.
- A request of a kind in the table has every required detail.
- **Request** has every question the docs did not answer, with every part, and only PostHog can answer it or do what it asks.
- Each "<your name> checked" line is a lookup you ran in this conversation.
- No credential or personal data about their users made it in.
- It fits on one screen.
