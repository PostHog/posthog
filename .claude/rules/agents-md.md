---
paths:
  - 'AGENTS.md'
  - 'CLAUDE.md'
  - '**/AGENTS.md'
  - '**/CLAUDE.md'
---

Invoke the `/editing-agents-md` skill before adding, editing, or removing any instruction here.

The root file loads in full at the start of every session, so a line added to it is paid for by
every task in the repo. The skill carries the ladder that decides whether a rule belongs in a
linter, a skill, or this file at all; the six smells to check the diff against; and the
`[lint: <id>]` / `[review]` tag convention that the root file's Architecture guidelines and Code
Style sections use.

Do not reorder sections to make a rule more prominent — instruction position has no measured
effect on whether an agent follows it. Reorder only to help a human find or cite a rule.
