# Simplified Technical English for PR descriptions

An evaluation, not a proposal to adopt.
The question: can we enforce ASD-STE100 in PR descriptions through `AGENTS.md` and `.github/pull_request_template.md`?

Short answer: those two files can ask for it, and neither can enforce it.
Enforcement needs a check that reads the PR body.
About half of STE is mechanically checkable; the half that carries most of its value is not, because the approved-word dictionary is licensed and cannot be checked into a public repo.

## What ASD-STE100 is

A controlled-language standard from the AeroSpace, Security and Defence Industries Association of Europe, maintained by the STE Maintenance Group.
It was written for aircraft maintenance manuals read by technicians whose first language is not English.
It has two halves:

- Roughly 65 writing rules. Sentence-length ceilings, active voice, no `-ing` verb forms, keep the articles, simple tenses, one instruction per sentence, no noun cluster longer than three words.
- A dictionary of roughly 900 approved words. Each word has one approved meaning and one approved part of speech. "Follow" means "come after", never "obey". "Test" is a noun, not a verb.

The specification is free on request from asd-ste100.org, under a license that does not allow redistribution.
That matters for enforcement: we cannot vendor the word list, so a checker in this repo would carry a hand-maintained subset and would not be STE conformance in any auditable sense.

## What the repo asks for today

`.github/pull_request_template.md` already sets a voice, and it is the opposite standard:

> Write with a crisp, direct Silicon Valley communication style. [...] Communicate as if you're explaining a complex concept to a smart colleague over coffee, keeping the tone light but substantive.

That instruction breaks three STE rules in one sentence: an idiom ("over coffee"), an `-ing` verb form ("keeping"), and a 20-word sentence carrying two ideas.
The two styles cannot both be in effect. Adopting STE means deleting the voice paragraph, not appending to it.

## Where they disagree

|                              | Silicon Valley voice (today)                 | ASD-STE100                                      |
| ---------------------------- | -------------------------------------------- | ----------------------------------------------- |
| Reader                       | A colleague who shares your context          | A technician who does not, in a second language |
| Purpose                      | Persuade a reviewer that the change is right | Remove every possible misreading                |
| Sentence length              | Whatever reads well                          | 20 words procedural, 25 descriptive             |
| Voice                        | Active, by taste                             | Active, by rule                                 |
| Vocabulary                   | Any word that lands                          | ~900 approved words, one meaning each           |
| Tone                         | Light but substantive                        | No tone. Tone is noise                          |
| Idiom, humor, understatement | Encouraged                                   | Banned                                          |
| `-ing` forms                 | Free                                         | Banned outside technical names                  |
| Tables, diagrams, links      | Encouraged, and the template pushes for them | Out of scope. STE says nothing about them       |
| Enforcement                  | Reviewer taste                               | Rule set plus licensed dictionary               |

The deepest disagreement is not style, it is purpose.
STE optimizes for a reader who must execute a procedure exactly and cannot ask a question.
A PR description optimizes for a reviewer who must judge whether a change is correct, and who can ask.
Those two readers want different text.

## Measured on 60 merged PRs

Corpus: the 60 most recent PRs merged by one author on this repo, 141,247 characters of body text.
Fenced code and mermaid are 7% of that, table rows 17%; the remaining 77% is prose, so STE would govern most of the text rather than a corner of it.
Prose was extracted by stripping code fences, mermaid, tables, headings, HTML comments and checkboxes, then sentence-split.
Passive voice and `-ing` detection are regex heuristics, so treat those two rows as indicative, not exact.

| Measure                                         | Value     |
| ----------------------------------------------- | --------- |
| Prose sentences                                 | 930       |
| Prose words                                     | 11,684    |
| Mean words per sentence                         | 12.6      |
| Sentences over 20 words (STE procedural limit)  | 142 (15%) |
| Sentences over 25 words (STE descriptive limit) | 63 (7%)   |
| Passive-voice hits                              | 78        |
| `-ing` verb forms                               | 318       |
| PRs already clean on all three                  | 1 of 60   |

The mean sentence is already well inside the STE ceiling.
The failures are concentrated: 15% of sentences carry the length problem, and 153 distinct `-ing` forms carry most of the rest ("failing" 30 times, "existing" 27, "writing" 15).
Vocabulary that a dictionary pass would replace, ranked by how many PRs contain it: "via" (16 PRs, approved equivalent "with"), "surface" as a verb (7), "shadow" as a verb (7), "burn" (3), plus filler words STE deletes outright, "just" (4) and "actually" (3).

Longest sentence in the corpus, 60 words, from [chore(data-modeling): freeze test clock at test start, not import](https://github.com/PostHog/posthog/pull/73628):

> Follow-ups, not in this PR: `products/batch_exports/backend/tests/temporal/test_monitoring.py` has the same module-level `NOW` + `@freeze_time(NOW)` shape (no S3 signing today, so latent); the Temporal CI job's `bin/ci-wait-for-docker wait` omits `objectstorage` while the core job waits for it explicitly; and that job's "Show docker compose logs on failure" step is gated to skip precisely when tests fail, which is what made this hard to diagnose.

## Before and after on shipped PRs

Word counts follow the measurement script: markdown stripped, and each inline code span counted as one word.

### 1. [fix(ci): recover jest shard identity in flat junit downloads](https://github.com/PostHog/posthog/pull/74003)

Shipped, 25 words, one sentence:

> When the signals job's artifact glob matches one artifact (every selective-mode run), `download-artifact` extracts it flat, so spans get `job_key junit-artifacts:junit-artifacts:None` and re-run recovery joins miss.

STE, 44 words, five sentences, longest 11:

> The signals job downloads the JUnit artifacts with a glob pattern. In selective mode, the pattern matches only one artifact. Then the download-artifact action extracts the files flat. The trace span gets the job key `junit-artifacts:junit-artifacts:None`. The re-run recovery cannot join on this key.

76% longer. It also states the causal chain as four separate facts instead of one clause pile, which is the actual gain: a reader can stop after any sentence and still be correct.

### 2. [fix(engineering-analytics): ignore fork PRs in run attribution](https://github.com/PostHog/posthog/pull/73969)

Shipped, 28 words, one sentence:

> GitHub's `pull_requests` association lists every PR in the fork network sharing the run's head SHA, so our master pushes arrive carrying downstream forks' open "sync from upstream" PRs.

STE, 39 words, three sentences, longest 18:

> The GitHub `pull_requests` association lists all pull requests with the same head SHA. This includes the pull requests of all forks. Thus a push to the master branch shows the open "sync from upstream" pull requests of the forks.

39% longer. Two participles go ("sharing", "carrying"), and the stacked possessives ("the run's", "forks'") flatten into prepositions.
"PR" survives only if the description defines the abbreviation once, which STE requires and no PR here does.

### 3. The 60-word sentence above

STE, 78 words, seven sentences, longest 20:

> This pull request does not correct three related problems. First, `test_monitoring.py` has the same module-level `NOW` and `@freeze_time(NOW)` shape. That test does not sign S3 requests today, thus the problem stays latent. Second, the wait command of the Temporal CI job does not include `objectstorage`. The core job waits for `objectstorage` explicitly. Third, the step "Show docker compose logs on failure" has a condition that skips the step when the tests fail. This condition made the diagnosis difficult.

30% longer, and the only rewrite here that is unambiguously better than what shipped.
A 60-word sentence with two semicolons is not a style preference, it is a defect.

### 4. The template's own voice rule

Shipped, 20 words:

> Communicate as if you're explaining a complex concept to a smart colleague over coffee, keeping the tone light but substantive.

STE, 12 words:

> Write short sentences. Give the necessary technical facts. Do not use idioms.

40% shorter, because the original sentence was mostly tone.
This is the one place STE reliably wins: instructions.

Across the four passages, 133 words become 173, a 30% increase.

## What enforcement would take

`AGENTS.md` and the PR template can only ask.
Nothing reads the PR body today, so agents and humans drift immediately.
A real check runs on `pull_request` (`opened`, `edited`, `synchronize`), pulls the body, strips code fences, mermaid, tables and HTML comments, then applies rules.

Checkable mechanically:

- Sentence length ceilings.
- `-ing` verb forms, with an allow list for technical names.
- Passive voice, at heuristic accuracy.
- A banned-word list, which is where the "no leverage, no utilize" rules already in `CLAUDE.md` live.
- Paragraph length.

Not checkable here:

- Approved-word conformance, the core of the standard. The dictionary is licensed. A hand-maintained subset drifts and gives false confidence.
- One meaning per word, one part of speech per word. Needs the dictionary plus part-of-speech tagging.
- Noun-cluster limits. Needs tagging; a regex over lowercase runs produces mostly noise, which is why that measurement is not in the table above.

So the honest ceiling is: we can enforce the STE writing rules that a linter can see, and we cannot claim STE conformance.

Tooling, if we do it: a prose linter such as Vale (a Go binary, rules in YAML, runs on markdown) reads a body dumped to a file, or a short Python check in an existing PR workflow.
The Python route avoids a new binary in CI and keeps the rules next to the repo's other PR checks.
Neither is written yet.

## Recommendation

Do not adopt ASD-STE100.
The standard is built for procedures executed by a reader who cannot ask a question, and a PR description is an argument made to a reviewer who can.
Its ban on tables and its silence on diagrams and links also collide with the parts of our template that make review faster.

Take the four rules that pay off, and enforce those:

1. Hard ceiling of 25 words per sentence. This is the one real defect in the corpus, and it is one regex.
2. Active voice in the Problem and Changes sections.
3. No `-ing` verb form where a simple tense works.
4. Extend the existing banned-word list with the STE substitutions that already match house style: "via" becomes "with", "surface" as a verb becomes "show", and delete "just", "actually", "simply".

That is a change to `AGENTS.md`, the template's authoring rules, and a body check in a PR workflow.
It gets most of the readability gain, keeps tables and diagrams, and does not claim a conformance we cannot verify.

## Reproducing the numbers

`docs/internal/pr-description-voice-ste-measure.py` regenerates every figure in this document.

```bash
gh pr list --author @me --state merged --limit 60 --json number,title,url,body > prs.json
python3 docs/internal/pr-description-voice-ste-measure.py prs.json
```
