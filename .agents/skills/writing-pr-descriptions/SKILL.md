---
name: writing-pr-descriptions
description: >
  Shapes a PR body into something a reviewer understands at a glance.
  Use ALWAYS before writing or editing a PR description, before `gh pr create` or `gh pr edit --body`, and when asked to improve an existing description.
  Routes each fact to the form that carries it fastest (bullet, table, diagram, screenshot, collapsed block), cuts everything a reviewer does not need, then holds what survives to a checkable shape: one fact per bullet, sentences under 25 words, active voice, no idioms.
  Ends with a self-check the agent runs over its own draft, including the test that the rewrite got shorter.
  Not for commit messages (see AGENTS.md, "Commit types") or user-facing product copy (see `/writing-user-facing-copy`).
---

# Writing PR descriptions

A reviewer scans a description in seconds and decides where to spend attention. The body is a scanning surface, not an essay. Everything below serves one goal: a reviewer understands the change without reading twice.

Work in four passes: route, cut, shape, check. Run all four.

## Pass 1: route each fact to a form

Prose is the slowest form on the page. Before writing a sentence, ask what carries the fact faster.

| The fact you have                                                                    | The form that carries it                                  |
| ------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| A visual change (any UI a person sees)                                               | Screenshot, before and after. Mandatory, not optional     |
| A change to a flow or topology (CI wiring, pipelines, state machines, request paths) | Two `flowchart` blocks, before first                      |
| Several values compared across the same dimensions                                   | A markdown table                                          |
| A config or setting change                                                           | A fenced `diff` block                                     |
| Existing code a reviewer needs to see                                                | A line-range permalink, which GitHub renders as a snippet |
| Test output, logs, long command transcripts                                          | A `<details>` block                                       |
| A behavior change or a risk a reviewer must not miss                                 | `> [!WARNING]` or `> [!NOTE]`                             |
| Anything else                                                                        | Bullets, under the shape rule in pass 3                   |

No PR needs every form. Reach for one because it makes review faster, never as decoration. An empty section gets one bullet or "None".

### Screenshots

Upload with `hogli pr:upload-image <file>` and paste the markdown it prints. The first run only warns; re-run with `--yes`. The assets are public forever, so never upload customer data, customer names, secrets, or internal info.

### Mermaid

Keep diagrams simple. A syntax error renders as an error block. Pick `TD` for tall pipelines, `LR` for wide paths. Mermaid cannot read CSS vars, so use the hex directly, and pair every `fill` with a text `color` so nodes stay legible in GitHub light and dark.

```text
classDef phBlue fill:#1d4aff,stroke:#1d4aff,color:#fff;
classDef phRed fill:#f54e00,stroke:#f54e00,color:#fff;
classDef phYellow fill:#f9bd2b,stroke:#f9bd2b,color:#000;
classDef phGray fill:#e5e7eb,stroke:#c7ccd1,color:#000;
```

Assign by role (`class NodeA,NodeB phBlue;`): `phBlue` agents and primary paths, `phRed` APIs and external systems, `phYellow` entry and exit, `phGray` data and artifacts. Shape by kind: `{{hexagon}}` agents, `[rect]` steps.

## Pass 2: cut

One fact per bullet makes prose checkable. It does not make it shorter: a dense paragraph exploded into twelve bullets moves the reviewer's cost rather than removing it.

So cut first, and shape only what survives. A fact earns a line when a reviewer needs it to judge the change, approve it, or know what to watch after it ships.

Delete:

- Anything reconstructable from the diff. The reviewer can read the code.
- Rationale for a choice nobody would question. Keep the reason only where you rejected an obvious alternative.
- Restatements of the title, and summaries of the sections above.
- Process narration. "Then I ran X, then Y" is a fact about your session, not about the change.
- Hedges on facts that are not in doubt.
- The follow-up sentence in any "here is the reason, and here is why the reason matters" pair.
- Any bullet whose reader you cannot name.

Budget, as a ceiling and not a target:

- A one-file fix: 3 to 6 bullets across the whole body.
- A typical PR: Problem and Changes together fit in about 10 bullets.
- Numbers, file paths and identifiers survive cutting. Adjectives and second explanations do not.

The test: **the body must come out shorter than your first draft.** Pass 4 checks it.

## Pass 3: shape what survives

The shape is checkable. Tone is not, which is why this skill does not ask for one.

1. One fact per bullet.
2. Sentences under 25 words.
3. Active voice, with a stated subject. Use the passive only where the actor is genuinely unknown or irrelevant.
4. Simple tenses. No perfect or progressive forms: "the builder took entry 1", not "the builder has been taking entry 1".
5. The same word for the same thing, every time. Never vary for style.
6. Keep the articles. "The job downloads the artifact", not "job downloads artifact".
7. Noun strings of at most three words. "The flag evaluation column codec" becomes "the codec on the flag evaluation column".
8. No idioms, no figurative language, no jokes.

A reviewer scans, stops, checks one claim, moves on. A sentence that packs four facts into three clauses makes them hold all four to check any one. Split it.

This governs prose only. A table cell is not a sentence, and a diagram is not prose.

### Worked example

❌ One bullet, five links in a causal chain, 28 words:

> When the signals job's artifact glob matches one artifact (every selective-mode run), `download-artifact` extracts it flat, so spans get `job_key ...:None` and re-run recovery joins miss.

✅ Three bullets, each checkable on its own, 22 words:

> - In selective mode, `download-artifact` extracts the files flat.
> - The span gets the job key `...:None`.
> - Re-run recovery cannot join on that key.

The cut removed the glob matching one artifact, which is the mechanism behind "in selective mode" and reachable from the diff. It kept every identifier, and every link in the chain a reviewer has to check.

Copy the second one. It is shorter, not just flatter.

### Other prose rules

- No em-dashes. Use en-dashes only if needed.
- Sentence case for titles, headings, and bolded text. Only the first word and proper nouns.
- Spare use of inline code. Limited use of the colon and semicolon.
- Do not hard-wrap at a column width and do not space-align tables. GitHub renders markdown and flows the text.
- Write in first person as the author. When an agent did the work, say so: "I (actually Claude) moved the derivation into one place."

## Pass 4: check your own draft

Run this over the body you just wrote, before `gh pr create` or `gh pr edit`. Fix what fails.

1. Is the body shorter than your first draft? If it is longer, you split without cutting. Go back to pass 2.
2. Read each bullet and name the reader who needs it. Delete the ones you cannot.
3. Read each bullet alone. Does it state one fact? If it states two, split it.
4. Count the words in the longest sentence. Over 25, split it.
5. Find every passive sentence. Rewrite it in active voice, unless the actor is genuinely unknown.
6. Find every noun string longer than three words. Break it with a preposition.
7. Does the PR change anything a person sees? If yes, is a screenshot in the body?
8. Does it change a flow or topology? If yes, are the before and after diagrams there?
9. Is any comparison sitting in prose that belongs in a table?
10. Is the `## 🤖 Agent context` section filled, listing the skills invoked?
11. Does the body claim manual testing that did not happen? Delete it.
12. Does the body name an internal customer, incident, Slack quote, or operational metric? This repo is public. Delete it.
13. Read the first three bullets only. Do they tell a reviewer what changed and why? If not, reorder.

## Background

`references/examples.md` runs two merged PRs through all four passes, with a table of what each cut removed and why. Read it when you want the rule applied end to end rather than to one sentence.

Pass 3 adapts a subset of the 53 writing rules in [ASD-STE100 Simplified Technical English](https://www.asd-ste100.org/) (Issue 9, January 2025). The 25-word ceiling is the standard's limit for descriptive text; it caps procedural text at 20, which a PR body rarely contains. Rule 1 is our own: STE writes "one instruction per sentence" for procedures and "one topic per paragraph" for descriptions, and a bullet sits between the two.

The other half of the standard, a dictionary of roughly 900 approved words each carrying one meaning, is licensed and deliberately not part of this. Vocabulary stays a judgment call.

Nothing here is enforced by a check. Pass 4 is the enforcement.
