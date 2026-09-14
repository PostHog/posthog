---
name: writing-pr-descriptions
description: >-
  Shapes a PR body into something a reviewer understands at a glance.
  Use ALWAYS before writing or editing a PR description, before `gh pr create` or `gh pr edit --body`, and when asked to improve one.
  Opens with the ground a reviewer needs (the components and concepts this PR touches, and how they fit), then the effect a person sees, then the mechanism.
  Routes each remaining fact to the form that carries it fastest (bullet, table, diagram, screenshot, collapsed block), then holds it to a checkable shape: one fact per bullet, sentences under 25 words, active voice.
  Cuts complexity rather than context: a body too short to hand over the author's model of the area fails like a bloated one.
  Makes the body stand alone for a reader who has never opened this directory, and links every claim to its evidence or labels it unchecked.
  Ends with a scan test over the title, the ground, and the first line of Changes.
  Not for commit messages or user-facing product copy (see `/writing-user-facing-copy`).
---

# Writing PR descriptions

A reviewer scans a description in seconds and decides where to spend attention.
The body is a scanning surface, not an essay, and it has to stand without the diff.
A body that narrates the code, or that would fit any PR equally well, teaches its reader to skip the next one.

It also has to stand without the reviewer's memory of the area.
You spent an hour building a model of these components. The reviewer arrives from a notification holding none of it.
A body that is too short to hand that model over fails the same way a bloated one does, and it is harder to spot, because it looks disciplined.

Order decides whether they understand the change at all.
Form and length only decide how fast.
So get the order right first, and never buy shape at the cost of it.

Work in five passes: orient, route, cut, shape, check. Run all five. When a body already exists, pass 0 comes first.

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

## Pass 1: orient, then lead with the effect

Problem opens with two moves, in this order: the ground, then the effect.
The rest of the body assumes the reviewer holds both.

### The ground

Two to four sentences naming the components and concepts this PR touches, and how they fit together.
Write them for a competent engineer who has never opened this directory.

- Name each component and say what it is for, in the vocabulary of the product rather than of the files.
- Say how one component reaches the next, where the change depends on that link.
- Stop at the edge of the change. The ground is what was already true. The mechanism is what your change does inside it.

The test for that edge: a ground sentence stays true if the PR is closed. A sentence that holds only because of this change, or only because of the bug, belongs below.

> Workflows run an ordered list of steps. Each step holds a config, and the config's `inputs` array declares the fields a person fills in. The workflow editor renders every step's config into a preview card before the workflow runs.

The ground earns its length from how unfamiliar the area is, never from how large the diff is.
A change to a surface everyone touches needs one clause. A change inside a codec, a Temporal workflow, a pooled connection path, or a product nobody else works on needs the full paragraph.
Cut a ground sentence because the reader already holds it, never because the body is getting long. "PostHog has feature flags" orients nobody.

Do not orient with a file tour. `preview.tsx` importing from `stepConfig.ts` is a fact about the repository, and the reviewer reads it faster in the diff.

### The effect

The first line after the ground is the one line you can count on being read.
You just spent an hour inside the mechanism, so the mechanism comes out first. Push it down and spend that line on what a person experiences.

- The effect line says what is different for a person, and who that person is. Name the surface they were on. Four shapes cover almost every PR:
  - A fix: what breaks, and for whom.
  - A feature: what someone could not do, and now can. "The SQL editor lets users join tables, but there is no way to attach a computed field to a table."
  - A refactor, a chore or an enabling change: who is blocked, what it costs them, or what class of failure it removes. Nobody sees it, but somebody is waiting.
  - A follow-up or a layer in a stack: what the earlier PR left undone, and what this one adds. Link that PR and assume nobody read it.
- If the effect line opens with a symbol, a file path, a class, or a setting, you led with the mechanism. Rewrite it.
- Size the problem in one clause where you know it: how many teams, how often, since when.
- The mechanism follows, in the order a reviewer has to check it.
- The first bullet of Changes is the change itself. Renames, regenerated snapshots and comment fixes go last.
- Every Changes bullet a person can notice says what they now see or do differently, then the mechanism under it. One user-facing line in Problem does not discharge this.
- Say in one line which part of Changes is mechanical. A reviewer cannot otherwise tell a purely internal change from a visible one you described as internal.
- If one part of the diff is riskier than the rest, name that part and say the rest is mechanical.

Most of the time you already wrote the effect and put it third. Move it up rather than writing a new sentence.

The effect line can be a bullet or a standalone sentence, whichever reads faster, but one sentence and never a paragraph.

### Worked example

❌ The first three bullets, as written:

> - The canvas runtime posts to the host with `port?.postMessage(...)`, so messages sent before the port exists are silently dropped.
> - The host delivers the MessagePort only after the artifact iframe's load event, which fires after the app's module scripts ran.
> - A `ph.query` issued while the app mounts is dropped and rejects 30 s later with "Canvas request timed out".

✅ The same three facts, reversed, under the ground they need:

> Canvas apps run in a sandboxed iframe and reach the host over a MessagePort. The host creates the port and hands it to the app. Every host call the app makes, `ph.query` included, goes through that port.
>
> - A canvas app that queries while it mounts hangs for 30 seconds, then fails with "Canvas request timed out".
> - The host delivers the MessagePort only after the iframe's load event, which fires after the app's module scripts ran.
> - `port?.postMessage(...)` drops anything posted before that.

The three bullets are the ones the author wrote, reversed. Nothing in them was cut.
The reviewer now knows what a port is for here before they are asked to care that one arrives late.

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

- The ground from pass 1. It is the one part of the body the diff cannot supply, so it is never what you cut to make room.
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

### Cut complexity, not context

What tires a reviewer is the sentences, not the count of them.
Four clauses welded into one, a five-word noun string, a term that shifts meaning between two bullets: each of those stops the reader and makes them reconstruct.
Ten plain bullets do not. So this pass has no word budget.

Cut what the delete list names, then hand everything that survives to pass 4.
A fact the reviewer needs to follow the change stays, however many bullets that takes.

The failure runs both ways:

- Too long: the reviewer cannot find the change under the narration.
- Too short: the reviewer reads the whole body and still cannot say what the components are or why this change is the right one.

The second failure has a signature. Every sentence is true, none is wasted, and the body only works for someone who already holds the author's model of the area.
That is a description written for the person who wrote the PR.

### Size tracks the change

A body that would fit any PR tells a reader nothing about this one. A reader who meets a few learns to skip them all.
When the diff is six lines in an area the team knows, the body has to read as the body of a six-line change.

- Length tracks how unfamiliar the area is and what the change costs if it is wrong, not the line count of the diff. A one-line fix in a billing path earns more body than a fifty-line rename.
- One line or "None" under every heading that does not apply. That is a complete answer, not a gap.
- Numbers, file paths and identifiers survive cutting. Adjectives and second explanations do not.

Small does not mean partial. A short body still carries the ground, why the change is necessary, and what it does.

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

The test: **every sentence that survives names something the reviewer needs, and none of them needs a second reading.** Pass 5 checks it.

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

Read only the title, the ground, the effect line, and the first bullet of Changes. Cover the rest.
Answer as a reader who has never opened this directory, not as the person who wrote the diff.

1. Do you know which parts of the system are in play, and what each is for?
2. Do you know what is different now, and for whom?
3. Do you know what this PR does about it?
4. Did you reach 2 and 3 without a symbol, a file path, or a class name?

A "no" anywhere means the body is ordered for the writer, not the reader. Go back to pass 1. Nothing in the line check can rescue a body that fails here.

### The line check

1. Does Problem open with the ground, before the effect line? If not, go back to pass 1.
2. Read the body with the diff closed, as someone who has never worked in this area. Can you name the components in play, say why the PR exists, and say what it does? If not, you cut something a reader needs.
3. Does any sentence need a second reading? Split it, or replace the word that stopped you.
4. Does the length of the body track how unfamiliar the area is and what the change costs if it is wrong? A six-line rename under a full-length body reads as filler.
5. Are Problem and Changes together longer than the sections under them? If not, cut the lower ones.
6. Read Changes alone. Can you say what a person will now see or do differently, or that nothing user-visible changed? If neither, go back to pass 1.
7. Read each bullet and name the reader who needs it. Delete the ones you cannot.
8. Read each bullet alone. Does it state one fact? If it states two, split it.
9. Count the words in the longest sentence. Over 25, split it.
10. Rewrite every passive sentence in active voice, unless the actor is genuinely unknown. Break every noun string longer than three words with a preposition.
11. Does any sentence take its author as the subject? Rewrite it around the change. "I", "me" and "my" appear nowhere.
12. Does the PR change anything a person sees? Include before-and-after screenshots, or say why nothing looks different.
13. Did you rewrite an existing body? Every image, video, link and ticked box a person put there still appears.
14. Does the PR change a flow or topology? Include branded before-and-after diagrams.
15. Does prose compare several values across the same dimensions? Replace it with a table.
16. Does every claim about what you ran, measured or saw link its evidence, or say it went unchecked? Descriptions of behavior need no link.
17. Did a `<!-- -->` template comment survive anywhere? That section is unfilled. Fill it or delete it.
18. Is the `## 🤖 Agent context` section filled, listing the skills invoked?
19. Does the body claim manual testing that did not happen? Delete it.
20. Does the body name an internal customer, incident, Slack quote, or operational metric? This repo is public. Delete it.

## Background

`references/examples.md` runs merged PRs through every pass, with a table of what each cut removed and why. Read it when you want the rules applied end to end rather than to one sentence.

Pass 1 rests on three findings.
Readers scan before they read: 15 of 19 participants in [NN/g's web writing study](https://www.nngroup.com/articles/concise-scannable-and-objective-how-to-write-for-the-web/) approached unfamiliar text by scanning, and a version that was concise, scannable and front-loaded measured 124% higher usability than the original.
What a scanner sees is the start of each line, so [the first words](https://www.nngroup.com/articles/first-2-words-a-signal-for-scanning/) decide whether the rest gets read at all.
And review time goes to understanding the change rather than to finding defects ([Bacchelli and Bird, ICSE 2013](https://sback.it/publications/icse2013.pdf)), which makes handing over that understanding the body's first job.
[Google's CL description guidance](https://google.github.io/eng-practices/review/developer/cl-descriptions.html) says the same thing, and grounds pass 3 too: the description carries the problem and the reason for this approach, with enough context for a reader who is not in the code.
The ground is that last clause, and it is the first thing a body loses when brevity becomes the goal.

Pass 4 adapts a subset of the 53 writing rules in [ASD-STE100 Simplified Technical English](https://www.asd-ste100.org/) (Issue 9, January 2025). The 25-word ceiling is the standard's limit for descriptive text; it caps procedural text at 20, which a PR body rarely contains. Rules 1 and 2 are our own: STE writes "one instruction per sentence" for procedures and "one topic per paragraph" for descriptions, and a bullet sits between the two, while front-loading comes from the scanning research above.

The other half of the standard, a dictionary of roughly 900 approved words each carrying one meaning, is licensed and deliberately not part of this. Vocabulary stays a judgment call.

Nothing here is enforced by a check. Pass 5 is the enforcement.
