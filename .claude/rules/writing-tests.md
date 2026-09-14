---
paths:
  - '**/test_*.py'
  - '**/*_test.py'
  - '**/tests.py'
  - '**/*.test.ts'
  - '**/*.test.tsx'
  - '**/*.spec.ts'
  - '**/*.spec.tsx'
---

Agents keep shipping low-value test bloat here — change-detector assertions,
redundant near-duplicates, sleep-laden waits, zero-assertion mock choreography.

If this change touches what a test asserts or how it sets up, you MUST invoke the
`/writing-tests` skill before writing it. It carries the value gate ("what realistic
regression does this catch that no existing test does?"), the "don't write it"
decision tree, and the efficiency bar.

There is no size threshold. One fixture and one assertion added to an existing block
is in scope, and the skill tells you to extend an existing test rather than write a
new one, so that is the shape most changes take.

Touching a test file for an unrelated reason (rename, formatter, import sort) is exempt.
