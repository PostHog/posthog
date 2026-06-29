---
paths:
  - '**/test_*.py'
  - '**/*_test.py'
  - '**/*.test.ts'
  - '**/*.test.tsx'
  - '**/*.spec.ts'
  - '**/*.spec.tsx'
---

Agents have a track record of shipping low-value tests here — change-detector
assertions, redundant near-duplicate cases, sleep-laden waits, and zero-assertion
mock choreography. Do not add to the pile.

If this change adds a new test or substantially alters an existing one, you MUST
invoke the `/writing-tests` skill before writing it. Every test earns its place:
name the realistic regression it catches that no existing test already does — if
you can't name one, do not write it. Collapse near-duplicates into parameterized
cases, assert observable behavior through the public interface (never implementation
details), and keep it deterministic and fast (no sleeps, no real network, cheapest
level that catches the bug).

Touching a test file for an unrelated reason (rename, formatter, import sort) is exempt.
