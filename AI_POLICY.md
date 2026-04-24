# AI contributions policy

PostHog is built with plenty of AI assistance.
This policy exists because of a growing volume of low-quality, AI-generated contributions that waste maintainer time.

## The standard

**You own what you submit.**
Understand your code, test it, and be ready to explain why it's correct and how it interacts with the rest of the system (without re-prompting an LLM).
This is no different from what we'd expect of any contribution; AI makes it easier to skip the work – please don't skip the work.

**Prove it works.**
Before submitting, please verify the change actually works end-to-end — don't rely on "it compiles" or "tests pass" alone.

- **Frontend changes:** include a short demo (screenshot, screen recording, or GIF) of the feature working in the PR description. Ideally you demo more than just the happy path.
- **Backend changes:** add tests for new behavior, and describe your test strategy in the PR description: what you tested, how you tested it, and what edge cases you considered.

PRs that clearly weren't run or tested will be closed under this policy.

**Disclose AI usage.**
Our [PR template](.github/pull_request_template.md) includes an LLM context section — please use it (most agents will pick it up automatically).
If an LLM co-authored or authored your PR, say so and leave context about the tools and session.
This helps reviewers calibrate.

**Prefer PRs over AI-generated issues.**
If AI helped you find a bug, fix it and open a pull request — don't paste the AI's output into an issue.
Unreviewed, AI-generated bug reports and security disclosures will be closed without response.

**Don't submit unsolicited AI-generated PR reviews.**
If you didn't write the code and aren't a maintainer, don't point an LLM at someone else's PR and leave its output as a review comment.
This is generally never helpful.

## What happens when contributions don't meet this bar

- **First time:** We'll close the PR/issue with a link to this policy and a brief explanation.
- **Two or more closures:** We'll block the account.

## Why we're not anti-AI

We think the best contributions in 2026 often involve AI.
A contributor who uses an LLM to help them understand unfamiliar code, draft a first pass, or catch edge cases they'd miss is probably _more_ productive than someone doing everything by hand.
The key difference is that they're driving the AI, not the other way around.

If you're new to open-source contributing and want to learn, we're genuinely happy to help — open an issue, ask questions, submit small PRs.
