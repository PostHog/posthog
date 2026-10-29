---
name: writing-pr-descriptions
description: >-
  Shapes a PR body so a reviewer can understand the problem and change quickly.
  Use ALWAYS before writing or editing a PR description, before `gh pr create` or `gh pr edit --body`, or when asked to improve a description.
  States who is affected and what is wrong for them in Problem, taken from a source and never invented, then the visible effect and mechanism in Changes.
  Selects bullets, tables, diagrams, screenshots, or collapsed blocks for each fact.
  Removes unnecessary detail and checks one fact per bullet, sentences under 25 words, active voice, and no idioms.
  Keeps the body complete without the diff, aims for 150 words and suggests a stack when the PR needs more, and links evidence or marks claims as unchecked.
  Checks the title and first lines of Problem and Changes.
  Not for commit messages (see AGENTS.md, "Commit types") or product copy (see `/writing-user-facing-copy`).
---

# Writing PR descriptions

A reviewer scans a description in seconds and decides where to spend attention.
The body is a scanning surface, not an essay, and it has to stand without the diff.
A body that narrates the code, or that would fit any PR equally well, teaches its reader to skip the next one.

Order decides whether they understand the change at all.
Form and length only decide how fast.
So get the order right first, and never buy shape at the cost of it.

Work in five passes: lead, route, cut, shape, check. Run all five. When a body already exists, pass 0 comes first.

## Pass 0: keep what the body already holds

`gh pr edit --body` replaces the whole body, so every part of your draft that has no home is gone the moment you push it.
An existing body holds work you cannot recreate: screenshots and recordings a person uploaded, links they collected, a checkbox they ticked, a note to a named reviewer.

Read the current body and edit it, rather than writing a fresh one over the top:

```sh
gh pr view <number> --json body --jq .body > pr-body.md
# edit pr-body.md
gh pr edit <number> --body-file pr-body.md
```

Carry every image, video, link and ticked box into the new body, under the heading it belongs to, and add the heading when your draft has none.
Replace one only when the change made it wrong, and say in the body that you replaced it.

## Pass 1: lead with the need

The first line is the one line you can count on being read.
You just spent an hour inside the mechanism, so the mechanism comes out first. Push it down and spend that line on the need that caused the work.

- Line 1 of Problem says who is affected and what is wrong for them today. Name the surface or workflow they were on. Four shapes cover almost every PR:
  - A fix: what breaks, and for whom.
  - A feature: what the person is trying to get done, and what stands in the way. "Analysts who join tables in the SQL editor recompute the same derived column in every query."
  - A refactor, a chore or an enabling change: who is blocked, what it costs them, or what class of failure it removes. Nobody sees it, but somebody is waiting.
  - A follow-up or a layer in a stack: what the earlier PR left undone, and what this one adds. Link that PR and assume nobody read it.
- Problem must stay true if the author picks a different solution. A missing version of your solution is not a problem: "there is no PDF export" is Changes with a "not" in it.
- Take the need from a source: the request, a linked issue, a thread, a measurement. The writer of a body often has only the diff. Never invent an actor, a cost, or a frequency to make the line read better. When no source gives the reason, say so in one line, so the reviewer knows to ask.
- If line 1 opens with a symbol, a file path, a class, or a setting, you led with the mechanism. Rewrite it.
- Size the problem in one clause where you know it: how many teams, how often, since when.
- The mechanism follows, in the order a reviewer has to check it.
- The first bullet of Changes is the change itself. Renames, regenerated snapshots and comment fixes go last.
- Every Changes bullet a person can notice says what they now see or do differently, then the mechanism under it. One user-facing line in Problem does not discharge this.
- Say in one line which part of Changes is mechanical. A reviewer cannot otherwise tell a purely internal change from a visible one you described as internal.
- If one part of the diff is riskier than the rest, name that part and say the rest is mechanical.

Most of the time you already wrote the need and put it third. Move it up rather than writing a new sentence.

Line 1 can be a bullet or a standalone sentence, whichever reads faster, but one sentence and never a paragraph.

### Solution-shaped problems

❌ The dashboard has no PDF export.

✅ Account managers rebuild weekly dashboard summaries in slides to send to customers (linked request).

✅ The request asks for a PDF export of a dashboard and gives no reason. (No source states the need, so the body says that and invents nothing.)

The first good version leaves room for more than one solution. The second is honest, and it tells the reviewer what to ask before approving.

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

| The fact you have                                                        | The form that carries it                                  |
| ------------------------------------------------------------------------ | --------------------------------------------------------- |
| A visual change (any UI a person sees, including a flow through screens) | Screenshot, before and after. Mandatory, not optional     |
| A new action and its effect, which one screenshot cannot show            | A feature reel in place of the "after" screenshot         |
| An architecture or topology change (defined under Mermaid)               | Two branded `flowchart` blocks, before first              |
| Several values compared across the same dimensions                       | A markdown table                                          |
| A config or setting change                                               | A fenced `diff` block                                     |
| Existing code a reviewer needs to see                                    | A line-range permalink, which GitHub renders as a snippet |
| Test output, logs, long command transcripts                              | A `<details>` block                                       |
| A behavior change or a risk a reviewer must not miss                     | `> [!WARNING]` or `> [!NOTE]`                             |
| Anything else                                                            | Bullets, under the shape rule in pass 4                   |

No PR needs every form. Reach for one because it makes review faster, never as decoration. An empty section gets one bullet: `- None.`

### Screenshots and reels

A screenshot is the default for every visual change.
A feature reel is an animated WebP of one UI flow, made with reel mode of `/qa-frontend`.
Use a reel only for a new action and its effect, when a screenshot of the end state hides the action.
Examples are a right-click menu on an element that had none, or a bar that appears when rows are selected.
A new item in an existing menu, a new column, or new copy gets a screenshot, because the reviewer already knows how a person gets there.
Before you make a reel, read `references/screenshots-and-reels.md`. It has the test, worked examples, and what a reel leaves out.

Take each screenshot from the first source that can show the change:

1. The running app, when one is up.
2. Storybook, through a headless browser. Use the story that covers the surface. When no story does, write a scratch story for the screenshot and keep it out of the commit.

Capture at `deviceScaleFactor: 2`. A 1x image looks soft on a high-density screen, and GitHub shrinks a wider image to fit the column. Take the before from the base branch the same way. A new surface has no before, so say that in one line.

Upload with `hogli pr:upload-image <file>` and paste the markdown it prints. The first run only warns; re-run with `--yes`. The assets are public forever, so never upload customer data, customer names, secrets, or internal info.

Touching UI code without a visible change is common, and the mandate has to be dischargeable. When nothing looks different, say so in one line. A reviewer cannot tell that case from a missing screenshot, and silence reads as the second.

### Mermaid

Draw before-and-after diagrams for every architecture or topology change, under one short sentence that states the change.
Architecture and topology mean CI wiring, pipelines, services and the calls between them, or module and package boundaries.
They also mean a state machine with several states, or a request path across systems.
This includes a small change, such as one step added to a straight chain or one fallback added to a lookup.
A reviewer sees a diagram at a glance, and can miss one sentence among the bullets.
The sentence gives a scanner the point, and the diagrams carry the flow, so the sentence never grows complex to explain it.
A UI flow or a linear sequence of screens is not a topology.
It gets screenshots or a reel, not a diagram.

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

❌ Three bullets from a real draft, each true:

> - The script prints 145 for this body and 199 for example 2.
> - `hogli lint:skills` passes.
> - The author decides whether to stack.

✅ Delete all three.
The first is a number the reviewer cannot use. CI already reports the second. The third tells the reviewer nothing to check or decide.

### 150 words

A body that would fit any PR tells a reader nothing about this one. A reader who meets a few learns to skip them all.
When the diff is six lines, the body has to read as the body of a six-line change.

- Aim for 150 words or fewer across the whole body, table cells included. A reviewer reads a table as closely as a bullet, so moving a sentence into one shortens nothing.
- Headings, diagrams, code blocks, images, HTML tags and `<details>` blocks do not count. Inline code counts.
- Moving evidence and transcripts into `<details>` is the first cut. Problem and Changes never move there: a reviewer skips collapsed text, so a fact they need stays visible and counts.
- The template's fixed lines, such as the release status and agent context labels, use about 25 of the 150 words.
- Give a one-file fix 3 to 6 bullets across the whole body.
- Write `- None.` under every heading that does not apply. That is a complete answer, not a gap. It is a bullet, like the release status line the changelog bot reads, so empty sections look the same.
- Keep numbers, file paths and identifiers when you cut. Cut adjectives and second explanations.

Run the counter on the body as GitHub stores it, after every `gh pr create` or `gh pr edit`, so you never paste the body twice. A new PR is a draft, so fix an over-count with `gh pr edit`:

```sh
gh pr view <number> --json body --jq .body | uv run .agents/skills/writing-pr-descriptions/scripts/count_words.py -
```

`uv run` installs the script's one dependency in its own environment and leaves the repo's virtualenv alone.

When the count is still over 150 after cutting, the PR is probably too big to review in one pass.
Suggest a stack to the PR author, name the layers you would split it into, and point to `/stacking-prs`.
The author decides. If they keep one PR, ship the shortest body that still carries the change.

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
- Agent context: autonomy, the tool with its exact model, and the skills invoked stay visible. Session notes, decisions and the rest go in the collapsed "More context for AI agents" block, in the template's field order.
- Rewrite that block on every push so it describes the PR at that commit. A stale block misleads the next agent more than an empty one.
- The reason your design beats the obvious alternative belongs in Changes. A reviewer needs it to review, and nobody scrolls past the release status section to find it.

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

1. Do you know who is affected, and what is wrong for them today?
2. Would the problem stay true if the implementation changed?
3. Do you know what this PR does about it?
4. Did you get there without a symbol, a file path, or a class name?

A "no" anywhere means the body is ordered for the writer, not the reader. Go back to pass 1. Nothing in the line check can rescue a body that fails here.

### The line check

1. Is the body shorter than your first draft? If it is longer, you split without cutting. Go back to pass 3.
2. Does the size of the body track the size of the diff, and does `scripts/count_words.py` print 150 or less? If not, cut, or suggest a stack as "150 words" says.
3. Are Problem and Changes together longer than the sections under them, with nothing of theirs inside `<details>`? If not, cut the lower ones.
4. Read the body with the diff closed. Can you say why the PR exists and what it does? If not, you cut something a reader needs.
5. Does Problem state a need that no source in the request, an issue, or a thread gave? Delete it, and say the reason was not given.
6. Read Changes alone. Can you say what a person will now see or do differently, or that nothing user-visible changed? If neither, go back to pass 1.
7. Read each bullet and name the reader who needs it. Delete the ones you cannot.
8. Read each bullet alone. Does it state one fact? If it states two, split it.
9. Count the words in the longest sentence. Over 25, split it.
10. Rewrite every passive sentence in active voice, unless the actor is genuinely unknown. Break every noun string longer than three words with a preposition.
11. Does any sentence take its author as the subject? Rewrite it around the change. "I", "me" and "my" appear nowhere.
12. Does the PR change anything a person sees? Include before-and-after screenshots, or say why nothing looks different.
13. Did you rewrite an existing body? Every image, video, link and ticked box a person put there still appears.
14. Does the PR change architecture or topology, as defined under Mermaid? Include branded before-and-after diagrams under one short sentence, also for a one-step change. Delete any diagram of a UI flow.
15. Does prose compare several values across the same dimensions? Replace it with a table.
16. Does every claim about what you ran, measured or saw link its evidence, or say it went unchecked? Descriptions of behavior need no link.
17. Did a `<!-- -->` template comment or any template placeholder text, such as `tool, model` or the bracketed test rationale, survive anywhere, collapsed blocks included? That field is unfilled. Fill it or delete it.
18. Is the `## 🤖 Agent context` section filled, naming the exact model and listing the skills invoked? Does the collapsed block still describe the PR as pushed?
19. Does the body claim manual testing that did not happen? Delete it.
20. Does the body name an internal customer, incident, Slack quote, or operational metric? This repo is public. Delete it.

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
