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
That includes "is this possible?" questions: a no from the docs is an answer, not a reason for a ticket.

A ticket is for something only PostHog staff can do or see:

- An action that staff run, such as deleting specific events, changing a bill, or restoring access to an account.
- Data or state on PostHog's side that neither of you can see.
- An error you reproduced that the docs do not explain.

Write one too when the person still wants a human after hearing the answer.
The ticket then says what the docs said and asks the one question that is left.
Your own conclusion that something is a PostHog bug is not enough.
Tell the person what you found, and offer a ticket.

The Support panel in PostHog offers a ticket only on a paid plan or an active trial.
Check the plan with `posthog:billing-subscription-get`.
On the free plan, say so before you write one, and point them to the community forum at https://posthog.com/questions.

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
Request: <what they need PostHog to do or answer, in their words>

Details:
- Project: <name>, ID <id>, <US or EU> Cloud, <link>
- <a required detail, a link to the object, or a fact>

Already checked:
- Docs: <link> says <what it says, in one line>
- <your name> checked: <the lookup, and what it showed>
- I tried: <a step the person took, and what happened>

Left for support: <the one thing only PostHog can do or confirm>

Error:
<exact text, top frames only>
```

- **Request** is one to three sentences. Keep their wording where you can. Add why only when it changes what support does. If they asked more than one question, put each on its own line, and trim a question without rewording it.
- **Already checked** keeps their steps ("I tried") apart from yours ("<your name> checked"), so support knows which ones happened in their app. When the docs had nothing, write "Docs: nothing found for <what you searched>".
- **Left for support** names one thing. For a request, it is the action, such as "Delete the 3,817 events this query returns".
- Copy IDs, queries and errors exactly.
- Keep it to about 150 words, not counting a query or an error.

Cut these before you hand it over:

- The story of the investigation. Keep what each check showed, and drop the narration.
- Your replies from the conversation, and guesses written as findings. Settle a guess before you write: ask the person when it is about their app, and when only PostHog could check it, make it the question in **Left for support**.
- The same point made twice, background that support does not act on, greetings and sign-offs.
- Whole event payloads and full stack traces.

Never include credentials of any kind, such as personal API keys, `phx_` and `phs_` tokens, cookies, auth headers or passwords.
Credentials often hide in error text, so read the error before you paste it, and say when you replaced something.
Leave out personal data about their users beyond one distinct ID or person link, and never include another customer's data.

## 4. Hand it over

Show the person the full ticket.
Tell them nothing is sent until they send it, and never say that a ticket was filed.
Do not promise a response time.

- If `posthog:posthog-support-draft-create` is in your tool list, draft the ticket with it. Each part of the ticket is one field: `request`, `details`, `already_checked`, `left_for_support` and `error`, without their headings. Give the person the `review_url` it returns. They open it, check the ticket, and send it from PostHog.
- Otherwise, they paste it into the Support panel in the PostHog app, which attaches their project and session to the ticket.

Say which details or links you could not find, so they can add them before they send it.

## Before you hand it over, check

- The docs did not already answer it.
- Every link came from a tool result, or from `posthog:docs-search` as it is.
- A request of a kind in the table has every required detail.
- **Left for support** names one thing, and only PostHog can do it.
- No credential or personal data about their users made it in.
- It fits on one screen.
