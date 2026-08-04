# What a PR description looks like in Simplified Technical English

Two of our own merged PRs, rewritten in ASD-STE100, next to what actually shipped.
The point is to see the difference and judge whether it reads better.
This is the reasoning behind the shape rule in `/writing-pr-descriptions`. Nothing here is enforced by a check.

## The standard, in short

ASD-STE100 is a controlled-language standard from the AeroSpace, Security and Defence Industries Association of Europe.
It was written for aircraft maintenance manuals read by technicians whose first language is not English.
It has two halves: 53 writing rules, and a dictionary of roughly 900 approved words where each word has one meaning and one part of speech.
Issue 9, released January 2025, is current.

The dictionary is licensed and cannot be redistributed, so the rewrites below follow the writing rules only.
That is also the honest ceiling on what a repo rule or an agent instruction can reproduce.

The rules that do the visible work:

1. One idea per sentence.
2. Procedural sentences stay under 20 words, descriptive sentences under 25.
3. Active voice, with a stated subject.
4. Simple tenses. No perfect or progressive forms.
5. No `-ing` verb forms outside technical names.
6. Keep the articles. "The job downloads the artifact", not "job downloads artifact".
7. Define an abbreviation the first time, then use it consistently.
8. No idioms, no understatement, no humor.
9. Use the same word for the same thing every time. Never vary for style.
10. Write sequential facts as separate sentences, not as one clause pile.

## Example 1: a short PR, in full

[fix(ci): recover jest shard identity in flat junit downloads](https://github.com/PostHog/posthog/pull/74003).

### As shipped

```markdown
## Problem

- When the signals job's artifact glob matches one artifact (every selective-mode run), `download-artifact` extracts it flat, so spans get `job_key junit-artifacts:junit-artifacts:None` ([example](https://github.com/PostHog/posthog/actions/runs/30283912832)) and re-run recovery joins miss.

## Changes

- Mark flat downloads; recover shard identity from the `junit-<segment>-<chunk>.xml` filename (jest only).

## How did you test this code?

- New parameterized test: recovered key equals the subdirectory layout's; non-matching filenames / pytest keep the fallback. Reporter suite 60/60.

## Docs update

None.

## 🤖 Agent context

**Autonomy:** Human-driven (agent-assisted). Bug found auditing live trace spans post-merge. Skills: `/writing-tests`, `/writing-code-comments`.
```

### In STE

```markdown
## Problem

- The signals job downloads the JUnit artifacts with a glob pattern.
- In selective mode, the pattern matches only one artifact.
- Then the `download-artifact` action extracts the files flat.
- The trace span gets the job key `junit-artifacts:junit-artifacts:None` ([example](https://github.com/PostHog/posthog/actions/runs/30283912832)).
- The re-run recovery cannot join on this key.

## Changes

- Mark the flat downloads.
- Get the shard identity from the file name `junit-<segment>-<chunk>.xml`.
- This applies to jest only.

## How did you test this code?

- A new parameterized test compares the two layouts.
- The recovered key is equal to the key from the subdirectory layout.
- Other file names and pytest use the fallback.
- The reporter test suite passes: 60 of 60 tests.

## Docs update

None.

## 🤖 Agent context

**Autonomy:** Human-driven (agent-assisted)

- An audit of the live trace spans after the merge found this defect.
- Skills: `/writing-tests`, `/writing-code-comments`.
```

Three sentences became eleven, and the prose is about 40% longer.
The shipped Problem is one 25-word sentence holding a five-step causal chain: the glob matches one file, the action extracts it flat, the key degrades, the join misses.
A reader has to hold four steps to reach the fifth. In STE each step stands on its own line and can be checked on its own.

## Example 2: a heavier PR

[fix(engineering-analytics): ignore fork PRs in run attribution](https://github.com/PostHog/posthog/pull/73969).
The three substantive sections only. The mermaid diagrams, tables and checkbox sections are left out, because STE says nothing about them and they do not change.

### As shipped

```markdown
## Problem

A push to master linked to a stranger's PR.

GitHub's `pull_requests` association lists every PR in the fork network sharing the run's head SHA, so our master pushes arrive carrying downstream forks' open "sync from upstream" PRs. The builder from [cost/friction lens + warehouse-shape fix](https://github.com/PostHog/posthog/pull/64421) took entry 1 unfiltered and paired that number with our own owner/name, linking an unrelated PR of ours. The same wrong key feeds `engineering_analytics_ci_job_history`, which is how the CI-breakage skill answers "master went red at SHA X, via PR Z".

## Changes

One derivation point, `logic/views/workflow_runs.py`. Everything downstream inherits it.

`ci_job_history` reads both keys off the builder now, collapsing a nesting layer that existed only to host [that regex](https://github.com/PostHog/posthog/pull/70556). Seed and `fixtures/fetch.py` keep the ids the filter needs; they stripped them before, so local seeds attributed nothing.

> [!NOTE]
> Query-time only. No migration, no backfill, existing rows unaffected.

## How did you test this code?

Against the live table, new expression vs old:

On a local stack, seeded and driven through the UI:

New tests: a builder case where a foreign entry is listed **first** and must not shadow ours (no existing fixture ever had a foreign entry, so nothing covered this), plus a `ci_job_history` master-push row carrying the fork network.

Green locally: 373 eng-analytics backend tests, 62 Jest, `tsgo`, repo-wide `mypy`, `hogli ci:preflight`.
```

### In STE

```markdown
## Problem

A push to the master branch linked to a pull request from a different repository.

- The GitHub `pull_requests` association lists all pull requests with the same head SHA.
- This includes the pull requests of all forks of this repository.
- Thus a push to the master branch also shows the open "sync from upstream" pull requests of the forks.
- The builder used the first entry of that list. It did not filter the entry.
- The builder joined that number to our own owner name and repository name.
- The result was a link to an unrelated pull request of this repository.
- The table `engineering_analytics_ci_job_history` uses the same incorrect key.
- The CI-breakage skill reads that table to find the pull request that made the master branch red.

## Changes

The change is in one file: `logic/views/workflow_runs.py`. All downstream code gets the new behavior.

- The `ci_job_history` view now reads the two keys from the builder.
- This removes one level of nesting. That level contained only the regular expression.
- The seed and `fixtures/fetch.py` keep the ids that the filter needs.
- They removed these ids before. Thus the local seeds showed no attribution.

> [!NOTE]
> The change applies at query time. There is no migration and no backfill. The existing rows do not change.

## How did you test this code?

I compared the new expression with the old expression on the live table.

I seeded a local stack and examined the result in the user interface.

- A new test puts a foreign entry first in the list. The builder must ignore that entry.
- No test fixture contained a foreign entry before, thus no test found this defect.
- A second new test adds a master-branch row that contains the fork entries.
- These tests passed locally: 373 engineering analytics backend tests, 62 Jest tests, `tsgo`, `mypy` on all files, and `hogli ci:preflight`.
```

What changed, and what it cost:

- The opener lost its edge. "A stranger's PR" is a good line, and STE cannot keep it, because "stranger" is not a technical word and the thing it produces is tone.
- The causal chain in the Problem became eight facts a reviewer can check one at a time. This is the clearest gain in either example.
- "Sharing", "carrying", "collapsing" and "auditing" all disappear. The stacked possessives ("the run's", "forks'", "the subdirectory layout's") flatten into prepositions. Longer, and unambiguous.
- One thing got worse in a way worth naming. The shipped text says the wrong key "is how the CI-breakage skill answers 'master went red at SHA X, via PR Z'". That clause tells a reviewer why the bug matters. The STE version states the same fact with the stakes drained out of it.
- The tables, mermaid diagrams and alert survive untouched, so the PR looks nearly the same on screen. Much of what makes these descriptions fast to scan is not prose, and STE does not reach it.

## How much would actually change

From the 60 most recent PRs merged by one author, with the script in the appendix.
The passive and `-ing` counts are regex heuristics, so read them as scale rather than exact counts.

| Measure                                              | Value                          |
| ---------------------------------------------------- | ------------------------------ |
| Prose sentences                                      | 938                            |
| Mean words per sentence                              | 12.5                           |
| Over the 20-word procedural limit                    | 143 (15%)                      |
| Over the 25-word descriptive limit                   | 63 (7%)                        |
| Passive-voice hits                                   | 77                             |
| `-ing` verb forms                                    | 320, across 154 distinct words |
| Share of body text that is prose, not tables or code | 77%                            |

The sentence-length rule is nearly free: the mean is 12.5 words, and only 7% of sentences pass the descriptive limit.
The `-ing` rule is where almost every PR fails, on ordinary words: "failing" 30 times, "existing" 27, "writing" 15.
Removing those costs little meaning, which says the rule is cheap to follow and, on its own, low value.

## What other teams do

No published example of a software team applying STE to pull request descriptions.
STE has spread out of aerospace into automotive, medical devices, pharmaceuticals and energy, all of them documentation for procedures, never change descriptions.
Where it appears in software, it governs the product docs, not the repository.

What the industry actually converged on, at three separate layers:

| Layer           | The standard                                                                                                                                                                                                                 | What it says                                                                                                                   |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Title           | [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)                                                                                                                                                       | `<type>(<scope>): <description>`. Already our rule                                                                             |
| Body            | [Google's "Writing good CL descriptions"](https://google.github.io/eng-practices/review/developer/cl-descriptions.html)                                                                                                      | First line is a complete imperative sentence. Then the problem, why this approach, its shortcomings, links to context          |
| Prose           | [Google developer documentation style guide](https://developers.google.com/style) and the [Microsoft Writing Style Guide](https://learn.microsoft.com/style-guide/welcome/), both shipped as [Vale](https://vale.sh/) styles | Active voice, short sentences, present tense, no jargon, define abbreviations                                                  |
| Above all of it | [ISO 24495-1:2023](https://www.iso.org/standard/78907.html), plain language                                                                                                                                                  | Short sentences, common words, logical structure. It explicitly separates plain language from controlled languages such as STE |

The two style guides overlap with STE on everything that made the rewrites above read better: active voice, one idea per sentence, short sentences, no idioms, consistent terms.
They leave out the parts that made the rewrites worse: the closed dictionary and the ban on any word chosen for effect.
Neither is licensed, and both already exist as machine-readable rule sets.

So the bullet-per-fact shape is not an STE invention. Every mainstream PR guide asks for it, in the words "use bullet points, not a wall of text".
STE is the strictest way to get there, and the only one that also forbids the vocabulary.

## What shipped with this document

Guidance, not a check, and no new skill. The rules live where an agent already looks before it opens a PR:

- `.github/pull_request_template.md`: the authoring rules now carry the style. This replaced the paragraph asking for "a crisp, direct Silicon Valley communication style" and a tone that is "light but substantive". STE has no tone, so the two could not both stay. An agent follows whichever it read last.
- `AGENTS.md`: the PR descriptions section states the style in one line and links here.

Two rules matter more than the rest:

- Apply this to prose. Leave the tables, diagrams and links alone, and never dissolve one back into prose.
- No PR needs every element. A one-file fix is a few bullets. A change to a flow earns a diagram. Form follows content.

The dictionary is not part of this. Vocabulary stays a judgment call, because the word list cannot be redistributed and a hand-maintained subset would drift.

## Appendix: reproducing the figures

```bash
gh pr list --author @me --state merged --limit 60 --json number,title,body > prs.json
python3 measure.py   # the script below
```

```python
import json, re, statistics
from collections import Counter

STRIP = [re.compile(p, f) for p, f in (
    ("`{3}.*?`{3}", re.S), (r"<!--.*?-->", re.S), (r"^\s*\|.*\|\s*$", re.M),
    (r"^#{1,6} .*$", re.M), (r"^\s*-\s*\[[ x]\].*$", re.M), (r"^>\s*\[!\w+\]\s*$", re.M),
)]
PASSIVE = re.compile(r"\b(is|are|was|were|be|been|being|gets?|got)\s+(\w+ed|written|run|done|kept|built|sent|made|taken|given|shown|known|found)\b", re.I)
ING = re.compile(r"\b(\w{4,}ing)\b", re.I)
ALLOWED = {"during", "everything", "nothing", "something", "string", "strings", "warning",
           "warnings", "setting", "settings", "timing", "logging", "tracing", "sharding",
           "engineering", "reporting", "meaning", "sibling", "siblings", "ceiling", "thing", "things"}
WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")

prs = json.load(open("prs.json"))
lengths, passive, ings = [], 0, []
chars = code = tables = 0

for pr in prs:
    body = pr["body"]
    chars += len(body)
    code += sum(len(m) for m in re.findall("`{3}.*?`{3}", body, re.S))
    tables += sum(len(m) for m in re.findall(r"^\s*\|.*\|\s*$", body, re.M))
    text = body
    for pattern in STRIP:
        text = pattern.sub("", text)
    text = re.sub(r"`[^`]*`", "CODE", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text))
    for line in filter(None, (line.strip() for line in text.split("\n"))):
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'`(])", line):
            if len(sentence.split()) < 3:
                continue
            n = len(WORD.findall(sentence))
            lengths.append(n)
            passive += len(PASSIVE.findall(sentence))
            ings += [w for w in ING.findall(sentence) if w.lower() not in ALLOWED]

print(f"sentences {len(lengths)}  mean {statistics.mean(lengths):.1f}")
print(f"over 20 {sum(n > 20 for n in lengths)}  over 25 {sum(n > 25 for n in lengths)}")
print(f"passive {passive}  -ing {len(ings)} ({len(set(w.lower() for w in ings))} distinct)")
print(f"code {100 * code / chars:.0f}%  tables {100 * tables / chars:.0f}%")
print(Counter(w.lower() for w in ings).most_common(3))
```
