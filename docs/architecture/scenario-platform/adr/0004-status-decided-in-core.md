# Core alone decides `passed`, `failed` or `invalid`

An adapter reports checks (`ready`, `validAfter`) and throws `AdapterError` when it cannot do its job. Core decides the status, in the order of today's `statusOf` (`nodejs/tests/scenarios/runner/status.ts`). The invalid list is checked first:

- dependencies down;
- failed checks;
- declared but not observed;
- under-offered;
- an unobserved valve;
- unknown pending;
- stray outcomes.

Only then do lost, duplicated or late units, or a broken bar, make the run `failed`.

An adapter returning its own status would let one adapter's `invalid` hide another adapter's loss. It would also let a team relabel a real failure as harness noise. A future reader may want to let adapters "own" their verdicts. This record says why they do not.
