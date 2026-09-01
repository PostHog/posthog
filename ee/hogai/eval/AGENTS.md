# Eval case data

Cases in this tree are committed to a public repository and are read by anyone.
Most CI evals run against the seeded Hedgebox project (the `demo_org_team_user` fixture in `ci/conftest.py`), and for those the case data is already synthetic.
Some evals supply their own case data inline instead — `ci/eval_ticket_summary.py` passes conversation transcripts straight into `EvalCase(input=...)`, because it evaluates a prompt rather than a query against a team.

This page is about that second kind.
When you write case data by hand, you are the only thing standing between a real conversation and a public repository.

## Write cases from a properties list, not from the source

Evals of support-facing features need cases that behave like real conversations, and you will often have a real one in front of you.
Do not edit it into shape.
Adapting real material and writing a fresh case are indistinguishable once you are partway through, and the result reads as synthetic while carrying somebody's actual words.

Work in this order instead:

1. Read the real material and write down only the **properties** a case has to exercise — a misspelling inside a quotable span, one word spelled two ways so a spliced quote can be caught, a mid-conversation topic change, an earlier summary sitting in the transcript, non-English text, a bare command with nothing to summarize.
2. Close the real material.
3. Write the cases from the properties list.

The list is the deliverable of step 1. If you skip writing it down, you will end up paraphrasing instead.

## Everything identifying is invented

Hostnames, emails, person and company names, IDs, cookies, and tokens in a case are made up, not anonymized versions of real ones.
Use reserved domains (`example.com`, `example.org` — RFC 2606) and obviously fake token values.

Customers paste credentials into support chats. A real cookie or a fragment of a real auth token has no business here even when it is expired, truncated, or not usable on its own.

## Do not claim a provenance you have not checked

"Written fresh" in a commit message is a factual claim, and reviewers rely on it.
Only write it if you did the properties-list procedure above.

If you are unsure whether a case drifted toward its source, check rather than assert: any shared run of roughly 40 characters or more means derived, not fresh.
A `lint-staged` warning (`.github/scripts/check-fixture-provenance.sh`) fires when a commit adds a batch of conversation-shaped case data, as a reminder to do this — it cannot tell whether the text is real, so it never blocks.

## Related

- [`AGENTS.md`](../../../AGENTS.md), "Public open source repo guidance" — what may reach any public artifact, not just eval data
- [`README.md`](./README.md) — running CI, sandboxed, and offline evals
- [`products/posthog_ai/evals/AGENTS.md`](../../../products/posthog_ai/evals/AGENTS.md) — the seeded Hedgebox taxonomy, for evals that run against a team
- `/writing-evals` covers `products/posthog_ai/evals/` and `products/*/evals/`, not this tree
