// Test cases for the hogvm-arity-belongs-in-spec-typescript rule.
// ruleid: hogvm-arity-belongs-in-spec-typescript
const badMin = { fn: () => null, minArgs: 1 }

// ruleid: hogvm-arity-belongs-in-spec-typescript
const badMax = { fn: () => null, maxArgs: 2 }

// ok: hogvm-arity-belongs-in-spec-typescript
const ok = { fn: () => null, description: 'lowercase' }
