---
paths:
  - '**/test_*.py'
  - '**/*_test.py'
  - '**/*.test.ts'
  - '**/*.test.tsx'
  - '**/*.spec.ts'
  - '**/*.spec.tsx'
---

If this change adds a new test or substantially alters an existing one, invoke the
`/writing-tests` skill before making changes. The skill carries the "what regression
does this catch?" value gate, the "don't write it" decision tree, and the rule to
parameterize near-duplicate cases. Touching a test file for an unrelated reason
(rename, formatter, import sort) does not require the skill.
