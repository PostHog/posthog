---
name: writing-pr-descriptions
description: >-
  Shapes a PR body into something a reviewer understands at a glance.
  Use ALWAYS before writing or editing a PR description, before `gh pr create` or `gh pr edit --body`, and when asked to improve an existing description.
  Puts the effect a person sees in the first line and the mechanism under it, routes each remaining fact to the form that carries it fastest (bullet, table, diagram, screenshot, collapsed block), cuts everything a reviewer does not need, then holds what survives to a checkable shape: one fact per bullet, sentences under 25 words, active voice, no idioms.
  Makes the body stand alone, so a reader who opens no files still knows why the PR is necessary and what it does, sizes the body to the change so a small PR reads as small, and makes every claim either linked to its evidence or labeled as unchecked.
  Ends with a scan test over the title and the first lines of Problem and Changes.
  Not for commit messages (see AGENTS.md, "Commit types") or user-facing product copy (see `/writing-user-facing-copy`).
---

# Writing PR descriptions

A reviewer scans a description in seconds and decides where to spend attention.
The body is a scanning surface, not an essay, and it has to stand without the diff.
A body that narrates the code, or that would fit any PR equally well, teaches its reader to skip the next one.

Order decides whether they understand the change at all.
Form and length only decide how fast.
So get the order right first, and never buy shape at the cost of it.

Work in five passes: lead, route, cut, shape, check. Run all five.

## Pass 1: lead with the effect

The first line is the one line you can count on being read.
You just spent an hour inside the mechanism, so the mechanism comes out first. Push it down and spend that line on what a person experiences.

- Line 1 of Problem says what is different for a person, and who that person is. Name the surface they were on. Four shapes cover almost every PR:
  - A fix: what breaks, and for whom.
  - A feature: what someone could not do, and now can. "The SQL editor lets users join tables, but there is no way to attach a computed field to a table."
  - A refactor, a chore or an enabling change: who is blocked, what it costs them, or what class of failure it removes. Nobody sees it, but somebody is waiting.
  - A follow-up or a layer in a stack: what the earlier PR left undone, and what this one adds. Link that PR and assume nobody read it.
- If line 1 opens with a symbol, a file path, a class, or a setting, you led with the mechanism. Rewrite it.
- Size the problem in one clause where you know it: how many teams, how often, since when.
- The mechanism follows, in the order a reviewer has to check it.
- The first bullet of Changes is the change itself. Renames, regenerated snapshots and comment fixes go last.
- Every Changes bullet a person can notice says what they now see or do differently, then the mechanism under it. One user-facing line in Problem does not discharge this.
- Say in one line which part of Changes is mechanical. A reviewer cannot otherwise tell a purely internal change from a visible one you described as internal.
- If one part of the diff is riskier than the rest, name that part and say the rest is mechanical.

Most of the time you already wrote the effect and put it third. Move it up rather than writing a new sentence.

Line 1 can be a bullet or a standalone sentence, whichever reads faster, but one sentence and never a paragraph.

### Worked example

❌ The first three bullets, as written:

> - The canvas runtime posts to the host with `port?.postMessage(...)`, so messages sent before the port exists are silently dropped.
> - The host delivers the MessagePort only after the artifact iframe's load event, which fires after the app's module scripts ran.
> - A `ph.query` issued while the app mounts is dropped and rejects 30 s later with "Canvas request timed out".

✅ The same three facts, reversed:

> - A canvas app that queries while it mounts hangs for 30 seconds, then fails with "Canvas request timed out".
> - The host delivers the MessagePort only after the iframe's load event, which fires after the app's module scripts ran.
> - `port?.postMessage(...)` drops anything posted before that.

Nothing was added and nothing was cut. The reviewer now knows the stakes before they reach the cause.

## Pass 2: route each fact to a form

Prose is the slowest form on the page. Before writing a sentence, ask what carries the fact faster.

| The fact you have                                                                    | The form that carries it                                  |
| ------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| A visual change (any UI a person sees)                                               | Screenshot, before and after. Mandatory, not optional     |
| A change to a flow or topology (CI wiring, pipelines, state machines, request paths) | Two branded `flowchart` blocks, before first              |
| Several values compared across the same dimensions                                   | A markdown table                                          |
| A config or setting change                                                           | A fenced `diff` block                                     |
| Existing code a reviewer needs to see                                                | A line-range permalink, which GitHub renders as a snippet |
| Test output, logs, long command transcripts                                          | A `<details>` block                                       |
| A behavior change or a risk a reviewer must not miss                                 | `> [!WARNING]` or `> [!NOTE]`                             |
| Anything else                                                                        | Bullets, under the shape rule in pass 4                   |

No PR needs every form. Reach for one because it makes review faster, never as decoration. An empty section gets one bullet or "None".

### Screenshots

Upload with `hogli pr:upload-image <file>` and paste the markdown it prints. The first run only warns; re-run with `--yes`. The assets are public forever, so never upload customer data, customer names, secrets, or internal info.

Touching UI code without a visible change is common, and the mandate has to be dischargeable. When nothing looks different, say so in one line. A reviewer cannot tell that case from a missing screenshot, and silence reads as the second.

### Mermaid

Keep diagrams simple. A syntax error renders as an error block. Pick `TD` for tall pipelines, `LR` for wide paths. Mermaid cannot read CSS vars, so use the hex directly, and pair every `fill` with a text `color` so nodes stay legible in GitHub light and dark.

```text
classDef phBlue fill:#1d4aff,stroke:#1d4aff,color:#fff;
classDef phRed fill:#f54e00,stroke:#f54e00,color:#fff;
classDef phYellow fill:#f9bd2b,stroke:#f9bd2b,color:#000;
classDef phGray fill:#e5e7eb,stroke:#c7ccd1,color:#000;
```

Assign by role (`class NodeA,NodeB phBlue;`): `phBlue` agents and primary paths, `phRed` APIs and external systems, `phYellow` entry and exit, `phGray` data and artifacts. Shape by kind: `{{hexagon}}` agents, `[rect]` steps.

## Pass 3: cut

The body has to stand on its own.
Do not assume the reviewer reads the diff first, or at all, or in the order you wrote it.
Many go straight to the code and come back only if the body earned it, so write for a reader who has opened no files.

Keep:

- Why the change is necessary.
- What it does, at a level that needs no files open.
- The alternative you rejected, the blast radius, what to watch after it ships, where to look first.
- What someone arriving from `git blame` in six months needs. They cannot ask you, and the review thread will not tell them.

Cut the detail the diff carries better: exact values, per-file narration, the mechanics of code a reviewer reads in context anyway.
The test is not "is this in the diff", because a diff holds every detail and none of the point.

One fact per bullet makes prose checkable. It does not make it shorter: a dense paragraph exploded into twelve bullets moves the reviewer's cost rather than removing it. Cut first, and shape only what survives.

Delete:

- Narration of the diff, file by file or line by line.
- Rationale for a choice nobody would question. Keep the reason only where you rejected an obvious alternative.
- Restatements of the title, and summaries of the sections above.
- Process narration. "Then I ran X, then Y" is a fact about your session, not about the change.
- Hedges on facts that are not in doubt.
- The follow-up sentence in any "here is the reason, and here is why the reason matters" pair.
- Any bullet whose reader you cannot name.

### Size tracks the change

A body that would fit any PR tells a reader nothing about this one. A reader who meets a few learns to skip them all.
When the diff is six lines, the body has to read as the body of a six-line change.

- A one-file fix: 3 to 6 bullets across the whole body.
- A typical PR: Problem and Changes together fit in about 10 bullets.
- One line or "None" under every heading that does not apply. That is a complete answer, not a gap.
- Numbers, file paths and identifiers survive cutting. Adjectives and second explanations do not.

Small does not mean partial. Three bullets still have to carry why the change is necessary and what it does.

### Claims a reader can check

The description is the only artifact in a PR that nothing validates. The code has CI. This has you, so make every claim cheap to disprove.

This governs claims about the world: what you ran, measured, or saw in production.
A statement about how the code behaves needs no link, because the reader checks it against the code.
"The fallback never fires" is the second kind. "One source has failed every run since May" is the first.

- Link the evidence: the failing run, the error tracking issue, a line-range permalink, the dashboard.
- Delete the claims CI already makes. "24 passed" and "mypy clean" cost a line, cannot be checked from the body, and the checks carry more authority.
- State what you did not check. "Not run: the database-backed suites, because this sandbox has no database" is the most credible line in most bodies and the cheapest to write.
- Never claim testing you did not do. One of those found later costs the reader's trust in every description you write afterwards.

### The sections under Changes

Problem and Changes carry the review.
Everything under them is evidence and provenance, and a reviewer reaches it last or never.
When the lower half outgrows the upper half, cut the lower half.

- Testing: name the regression each new test catches, under the claim rules above. Transcripts go in a `<details>` block.
- Agent context: autonomy, tools, skills invoked, and what changed across the session.
- The reason your design beats the obvious alternative belongs in Changes. A reviewer needs it to review, and nobody scrolls past the changelog checkbox to find it.

The test: **the body must come out shorter than your first draft.** Pass 5 checks it.

## Pass 4: shape what survives

The shape is checkable. Tone is not, which is why this skill does not ask for one.

1. One fact per bullet.
2. Front-load the bullet. A scanner sees the first few words, so start with the subject that carries the fact, not the condition it holds under.
3. Sentences under 25 words.
4. Active voice, with a stated subject. Use the passive only where the actor is genuinely unknown or irrelevant.
5. Simple tenses. No perfect or progressive forms: "the builder took entry 1", not "the builder has been taking entry 1".
6. The same word for the same thing, every time. Never vary for style.
7. Keep the articles. "The job downloads the artifact", not "job downloads artifact".
8. Noun strings of at most three words. "The flag evaluation column codec" becomes "the codec on the flag evaluation column".
9. No idioms, no figurative language, no jokes.

Rule 2 orders the words inside a bullet. Pass 1 orders the bullets. They never conflict: the effect goes first, and the bullet that states it starts with the person it happened to.

A reviewer scans, stops, checks one claim, moves on. A sentence that packs four facts into three clauses makes them hold all four to check any one. Split it.

This governs prose only. A table cell is not a sentence, and a diagram is not prose.

### Worked example

❌ One bullet, five links in a causal chain, 28 words:

> When the signals job's artifact glob matches one artifact (every selective-mode run), `download-artifact` extracts it flat, so spans get `job_key ...:None` and re-run recovery joins miss.

✅ Three bullets, each checkable on its own, 22 words:

> - `download-artifact` extracts the files flat in selective mode.
> - The span gets the job key `...:None`.
> - Re-run recovery cannot join on that key.

The cut removed the glob matching one artifact. That is one level below what a reader needs, and "in selective mode" still names the condition. It kept every identifier, and every link in the chain a reviewer has to check.

Copy the second one. It is shorter, not just flatter.

### Other prose rules

- No em-dashes. Use en-dashes only if needed.
- Sentence case for titles, headings, and bolded text. Only the first word and proper nouns.
- Spare use of inline code. Limited use of the colon and semicolon.
- Do not hard-wrap at a column width and do not space-align tables. GitHub renders markdown and flows the text.
- The subject of a sentence is the change, not its author. Never "I", "me" or "my", and keep "we" for PostHog.
  "The exporter now retries once", never "I made the exporter retry once".
  An agent writing as "I" hands the assignee an account of work they did not do, and a parenthetical does not undo it.
  Authorship is one stated fact in `## 🤖 Agent context`, not a voice the body speaks in.

## Pass 5: check your own draft

Run both checks over the body you just wrote, before `gh pr create` or `gh pr edit`. Fix what fails.

### The scan test

Read only the title, the first line of Problem, and the first bullet of Changes. Cover the rest.

1. Do you know what is different now, and for whom?
2. Do you know what this PR does about it?
3. Did you get there without a symbol, a file path, or a class name?

A "no" anywhere means the body is ordered for the writer, not the reader. Go back to pass 1. Nothing in the line check can rescue a body that fails here.

### The line check

1. Is the body shorter than your first draft? If it is longer, you split without cutting. Go back to pass 3.
2. Does the size of the body track the size of the diff? A six-line change under a full-length body reads as filler.
3. Are Problem and Changes together longer than the sections under them? If not, cut the lower ones.
4. Read the body with the diff closed. Can you say why the PR exists and what it does? If not, you cut something a reader needs.
5. Read Changes alone. Can you say what a person will now see or do differently, or that nothing user-visible changed? If neither, go back to pass 1.
6. Read each bullet and name the reader who needs it. Delete the ones you cannot.
7. Read each bullet alone. Does it state one fact? If it states two, split it.
8. Count the words in the longest sentence. Over 25, split it.
9. Rewrite every passive sentence in active voice, unless the actor is genuinely unknown. Break every noun string longer than three words with a preposition.
10. Does any sentence take its author as the subject? Rewrite it around the change. "I", "me" and "my" appear nowhere.
11. Does the PR change anything a person sees? Include before-and-after screenshots, or say why nothing looks different.
12. Does the PR change a flow or topology? Include branded before-and-after diagrams.
13. Does prose compare several values across the same dimensions? Replace it with a table.
14. Does every claim about what you ran, measured or saw link its evidence, or say it went unchecked? Descriptions of behavior need no link.
15. Did a `<!-- -->` template comment survive anywhere? That section is unfilled. Fill it or delete it.
16. Is the `## 🤖 Agent context` section filled, listing the skills invoked?
17. Does the body claim manual testing that did not happen? Delete it.
18. Does the body name an internal customer, incident, Slack quote, or operational metric? This repo is public. Delete it.

## Background

`references/examples.md` runs merged PRs through every pass, with a table of what each cut removed and why. Read it when you want the rules applied end to end rather than to one sentence.

Pass 1 rests on three findings.
Readers scan before they read: 15 of 19 participants in [NN/g's web writing study](https://www.nngroup.com/articles/concise-scannable-and-objective-how-to-write-for-the-web/) approached unfamiliar text by scanning, and a version that was concise, scannable and front-loaded measured 124% higher usability than the original.
What a scanner sees is the start of each line, so [the first words](https://www.nngroup.com/articles/first-2-words-a-signal-for-scanning/) decide whether the rest gets read at all.
And review time goes to understanding the change rather than to finding defects ([Bacchelli and Bird, ICSE 2013](https://sback.it/publications/icse2013.pdf)), which makes handing over that understanding the body's first job.
[Google's CL description guidance](https://google.github.io/eng-practices/review/developer/cl-descriptions.html) says the same thing, and grounds pass 3 too: the description carries the problem and the reason for this approach, with enough context for a reader who is not in the code.

Pass 4 adapts a subset of the 53 writing rules in [ASD-STE100 Simplified Technical English](https://www.asd-ste100.org/) (Issue 9, January 2025). The 25-word ceiling is the standard's limit for descriptive text; it caps procedural text at 20, which a PR body rarely contains. Rules 1 and 2 are our own: STE writes "one instruction per sentence" for procedures and "one topic per paragraph" for descriptions, and a bullet sits between the two, while front-loading comes from the scanning research above.

The other half of the standard, a dictionary of roughly 900 approved words each carrying one meaning, is licensed and deliberately not part of this. Vocabulary stays a judgment call.

Nothing here is enforced by a check. Pass 5 is the enforcement.
