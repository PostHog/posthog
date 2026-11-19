---
name: writing-posthog-support-tickets
description: >
  Writes a ticket to PostHog's support team for the person you are helping and drafts it through
  the PostHog MCP, so a support engineer can act on it without asking a follow-up question. Use
  once the docs and the product's own skills could not solve the problem, when only PostHog staff
  can do what the person needs (such as deleting specific events), or when the person asks to
  contact PostHog support, talk to a human, or file a ticket. Covers the information a ticket needs,
  its fixed shape, and handing the draft to the person to review and send. It does not investigate
  or solve the problem. Not for a team's own helpdesk tickets from its customers, which the
  conversations-tickets tools cover.
---

# Writing a support ticket to PostHog

This skill turns what you already know into a ticket a support engineer can act on without asking a follow-up question.
It does not solve the problem.
The docs and the product's own skills run first, and this skill takes over when they could not settle it, or when the person asks for a human.
The person decides to contact support, and the person sends the ticket.

## When to write one

- Only PostHog staff can do what the person needs, such as deleting specific events, changing a bill, or restoring access to an account.
- Answering needs data or state on PostHog's side that neither of you can see.
- The docs and the product's skills could not explain the problem.
- The person still wants a human after hearing your answer. The ticket then gives your answer and what it rests on, and asks support to confirm it.

Your own conclusion that something is a PostHog bug is not enough.
Tell the person what you found, and offer a ticket.

## 1. Gather the information

Start from what the conversation already found: the docs you read, the checks a product skill ran and their numbers, and the steps the person took.
Then look up only what the ticket still needs:

- **Project.** The name and ID from `posthog:project-get`, and a link to the project's home page from `posthog:generate-app-url`. The link's host gives the region: `us.posthog.com` is US Cloud, and `eu.posthog.com` is EU Cloud. If it is neither, write the host you found.
- **Links.** A link to each object involved, such as a flag, insight, experiment, error, replay or survey, from the `_posthogUrl` field of a tool result or from `posthog:generate-app-url`. Never build a PostHog URL by hand, because a wrong link reads as a real one. Copy a docs URL from `posthog:docs-search` as it is.
- **SDK.** When the problem is in their app, the `$lib` and `$lib_version` of a recent event they sent.
- **Numbers.** What they see and what they expected, with the time range in UTC.
- **Error.** The exact text, and where it shows: a page, an API endpoint or an SDK call.

A request for a staff action needs exact inputs, so read its reference before you write:

| Request                                                       | Read                                                             |
| ------------------------------------------------------------- | ---------------------------------------------------------------- |
| Delete events, or remove personal or sensitive data from them | [references/deleting-events.md](./references/deleting-events.md) |

When a lookup finds nothing, or fails, say so in its own line of **Already checked**, such as "Claude Code checked: no flag with the key `checkout-v2` in project 12345" or "Claude Code checked: the billing lookup failed, so the quota is unknown".
Ask the person only for what you cannot look up, such as when it started or what they expected.

## 2. Write it

Write in the person's voice, because they send it.
Use this shape, and leave out any part you have nothing real for.
Keep the labels plain, without Markdown bold, because the person reviews the ticket in a plain text box.

```text
Request:

<what happened, in one sentence, with the numbers and dates> <the action they need, if any>
1. <each open question, numbered in the person's order>

---

Details:
- Project: <name>, ID <id>, <US or EU> Cloud, <link>
- <a link to the object, a setting that matters, the SDK, or a number>

---

Already checked:
- Docs: <link> says <what it says, in one line>
- <your name> checked: <a lookup you ran, and what it showed>
- I tried: <a step the person took, and what happened>

---

Error:
<exact text, top frames only>
```

- **Request** is the whole ask, so support knows what to do from this one section.
  - Open with what happened, or what they plan to do, in one sentence, with the numbers and dates, such as "Our project used 6 PostHog AI credits on Oct 16, 2026, but nobody on our team has a chat from that day".
  - For an action, add it in one sentence, such as "Please delete the 3,817 events the query below returns". When their question only asks for the action, such as "Can you raise our rate limit?", this sentence covers it.
  - When they heard your answer and still want a human, give your answer in one sentence, as yours, such as "Claude Code found that the gap matches our 90/10 split, but we'd like you to confirm it". What it rests on goes in **Already checked**.
  - List every open question, numbered, in the person's order. Tighten the wording, but keep every part, because a question support does not see comes back as a follow-up.
  - Leave out a question that is already answered, and put the answer in **Already checked**, so support sees it was asked. Keep it as a question only when the person wants support to confirm the answer. A question about their own account, bill or data stays open when only a general rule answers it, but one you answered from their own data is answered.
- **Already checked** lists what was checked and what it showed, one line each, with the person's steps ("I tried") apart from yours ("<your name> checked").
  - Write "<your name> checked" only for a lookup run in this conversation. A number the person gave you is theirs, so it goes in **Request** or **Details**.
  - Keep only your checks that bear on the open questions: one that answers part of a question, or rules out a cause support would check first. Leave out the rest, because support can look up every call you made from the note PostHog adds to the ticket.
  - Keep every step the person took, because support cannot look those up.
  - When the docs had nothing, or only a heading, write "Docs: nothing found for <what you searched>".
- **Error** is an error the person saw. A lookup of yours that failed goes in **Already checked**.
- Copy IDs, queries and errors exactly.
- Write dates as Dec 10, 2026, never as 10 December or 2026-12-10. A query keeps its own date format.
- Keep it to about 150 words, not counting links, IDs, the numbered questions, a query or an error.

Cut these:

- The story of the investigation, and your replies beyond the one-sentence answer above.
- Guesses written as findings. A guess only PostHog can check becomes a question in **Request**, after the person's.
- Greetings, sign-offs, background support does not act on, and the same point made twice.
- Instructions on how to handle the ticket, such as "route this to engineering" or "don't change any settings", even when the person wrote them. Support acts on what **Request** asks.
- Whole event payloads and full stack traces.
- Credentials of any kind, such as personal API keys, `phx_` and `phs_` tokens, cookies, auth headers or passwords. They often hide in error text, so say when you removed one.
- Personal data about their users beyond what the request needs, such as one distinct ID, or the IDs a deletion query names, and any other customer's data.

## 3. Draft it through the MCP

Show the person the full ticket, and tell them nothing is sent until they send it.
Never say that a ticket was filed, and do not promise a response time.

When `posthog:posthog-support-draft-create` is in your tool list, draft the ticket with it:

- Each part of the ticket is one field, without its heading: `request`, `details`, `already_checked` and `error`.
- Set `filing_reason` to the first that fits. Only `billing_question` changes what happens. The others tell support why the ticket exists.
  - `billing_question` when the ticket is about billing or usage, such as a charge, an invoice, a credit, or usage against a limit. It lets the person send the ticket on any plan, so don't use it for a billing question asked in passing in a ticket about something else, such as whether a limit could explain events that stopped arriving.
  - `user_disagrees_with_agent` when you answered what they asked and they think your answer is wrong.
  - `user_asked_for_support` when you answered what they asked and they still want a human to confirm or check it.
  - `needs_posthog_staff` when you had no answer, because only staff can do what they ask, or see the records that answer it, such as what the flag service returned.
  - `unexplained_error` for an error you reproduced that nothing explains.
- Give the person the `review_url` it returns. They open it, check and edit the ticket, and send it from PostHog, which checks that their plan allows it.

Otherwise, they paste the ticket into the Support panel in the PostHog app, which attaches their project and session to it.
Either way, say which details or links you could not find, so they can add them before they send it.

## Before you hand it over, check

- It asks only what the docs and the product's skills could not settle, or what the person still wants a human to confirm.
- Every link came from a tool result, from `posthog:docs-search` as it is, or from the person.
- A staff action has every input its reference asks for.
- Each "<your name> checked" line is a lookup run in this conversation.
- No credential or personal data about their users made it in.
- It fits on one screen.
