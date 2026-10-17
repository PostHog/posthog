---
name: resolving-review-findings
description: >
  Handle review findings on a PostHog/posthog pull request, above all the inline comments from
  PostHog Review (the `posthog[bot]` app, internal name ReviewHog). Use when addressing, replying to,
  or resolving review threads, or when babysitting a PR whose bot findings need an answer. Covers the
  👍/👎 verdict reaction on each finding, the fix or the reply, and resolving the thread.
---

# Resolving review findings

PostHog Review is PostHog's own code review bot.
It posts as the PostHog GitHub app: `posthog[bot]` in the REST API, `posthog` (a `Bot`) in GraphQL.
ReviewHog is its internal name in code; use "PostHog Review" in replies and PR text.

Each finding is an inline review comment whose first line is `**P{n} · {title}**`:
P1 is must fix, P2 should fix, P3 consider.

## Why the reaction matters

A reply or a commit does not tell review metrics whether the finding was right.
"Fixed in abc123" and "Keeping this as is" both read as engagement, and a finding that led to no code change could be noise or a valid point that was deferred.
The 👍 or 👎 on the finding comment is the one signal that says which, so every finding gets one.

## Per finding

1. Read the finding against the current code. Decide if it is valid. Do not trust the priority or the claim without checking.
2. React on the **finding comment itself** (the first comment of the thread, not your reply):
   - 👍 (`+1`) — the finding is valid, also when you defer the fix.
   - 👎 (`-1`) — the finding is wrong, already handled, or not worth acting on.
3. Act:
   - Valid: fix it, push, and reply with the commit SHA and one line on the fix.
   - Valid but out of scope: reply where the follow-up lives (an issue, a later PR).
   - Not valid: reply with the one-line reason.
4. Resolve the thread.

Never react with 👀: PostHog Review puts 👀 on threads it queues for its own resolution stage.
Findings listed only in the review body have no thread to react on. Handle them in code the same way and say what you did in one PR comment.
The same flow works for other review bots' threads (Codex, Greptile). PostHog Review is the one that must always get the reaction.

## Commands

List the open threads with their first comment:

```sh
gh api graphql -F owner=PostHog -F repo=posthog -F pr=<n> -f query='
  query($owner: String!, $repo: String!, $pr: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $pr) {
        reviewThreads(first: 100) {
          nodes { id isResolved comments(first: 1) { nodes { databaseId author { login } body } } }
        }
      }
    }
  }' --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved | not)'
```

React, reply, and resolve (`<comment-id>` is the first comment's `databaseId`, `<thread-id>` the thread `id`):

```sh
gh api -X POST repos/PostHog/posthog/pulls/comments/<comment-id>/reactions -f content=+1   # or -1
gh api -X POST repos/PostHog/posthog/pulls/<n>/comments/<comment-id>/replies -f body='Fixed in <sha>: ...'
gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "<thread-id>"}) { thread { isResolved } } }'
```

Reply after the fix is pushed, so the SHA in the reply exists on the PR.
