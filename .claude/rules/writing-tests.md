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

If this change adds a new test or substantially alters an existing one, you MUST
invoke the `/writing-tests` skill before writing it. It carries the value gate
("what realistic regression does this catch that no existing test does?"), the
"don't write it" decision tree, and the efficiency bar. Do not skip it because the
change looks small.

Touching a test file for an unrelated reason (rename, formatter, import sort) is exempt.
