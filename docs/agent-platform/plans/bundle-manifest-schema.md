# Design — bundle manifest schema (spec-derived allowlist)

**Status:** draft. **Owner:** Ben. **Tracking:** [`_TODO.md`](_TODO.md)
"Bundle manifest schema."

## 1. Problem

Today the janitor accepts any `{ path → text }` record on its bundle
write paths, so dev-only files (`spec.json`, `README.md`,
`scripts/seed.py`) end up in live bundles. Confirmed in the shipped
concierge fixture. There's no single source of truth for "what counts
as a bundle file" — the runner only consumes a subset of what gets
uploaded, the rest is dead weight at best and a leak vector at worst.

## 2. Working model — allowed iff referenced by spec

A path is allowed in a bundle iff it appears in the spec-derived set:

- `spec.entrypoint`
- Each `spec.skills[i].path`
- Each `spec.tools[i].path` (custom tools) — plus the two siblings the
  sandbox loads: `<path>/compiled.js` and `<path>/schema.json`

Anything not in the spec-derived set → reject at write time with a
structured 422 that lists the rejections with file paths and an
unambiguous reason ("file not referenced by spec.entrypoint, any
spec.skills[i].path, or any spec.tools[i].path").

## 3. Why not a path-shape allowlist (my first sketch)?

The natural-looking alternative is a regex / glob allowlist:

```text
allowed = ['agent.md', 'skills/**/*.md', 'tools/**/{compiled.js,schema.json}']
```

This doesn't work because `spec.entrypoint` and custom-tool `path` are
`z.string()` (author-defined) — a bundle that names its entrypoint
`prompts/main.md` should be just as legal as one that uses `agent.md`.
The contract has to be "referenced," not "matches a regex."

## 4. Coupled work

1. **Drop `tests/*.json` from the runtime bundle entirely.** The seed
   script currently uploads these but `validate-spec.ts` doesn't read
   them — they're harness-side fixtures, not runtime artifacts.
2. **One-off `scrub_bundle_paths` management command.** Sweeps live
   bundles, deletes paths that wouldn't pass the new write-time check.
   Run-once-before-enforce so the hard fail doesn't break existing
   deployed agents.
3. **Mirror the same check client-side in the console file-explorer.**
   The UX should reject the upload as the author types, not just at
   commit time.

## 5. Where the validation primitive lives

Likely in `services/agent-shared/src/spec/` next to `AgentSpecSchema`
so the runner + janitor + console + future authoring tools all agree.
Shape:

```typescript
export function deriveBundleAllowlist(spec: AgentSpec): Set<string> {
  const out = new Set<string>([spec.entrypoint])
  for (const skill of spec.skills) {
    out.add(skill.path)
  }
  for (const tool of spec.tools) {
    if (tool.kind === 'custom') {
      const base = tool.path.replace(/\/$/, '')
      out.add(`${base}/compiled.js`)
      out.add(`${base}/schema.json`)
    }
  }
  return out
}
```

The janitor's bundle-write handler calls this, intersects with the
incoming `{ path → text }` map, returns 422 for anything outside the
allowlist.

## 6. Open questions

1. **What about README.md inside skills?** Some authors might want a
   sibling README per skill for human review. The reference set
   doesn't permit it. Either: (a) extend `SkillRefSchema` with an
   optional `docs?: string[]`, or (b) declare README files outside the
   bundle scope (live in the source repo, not the deployed bundle).
   Lean (b) — the bundle is for the runtime, not the source.
2. **Migration semantics for existing bundles.** Run-once scrub before
   enforce, or fail-open + warn for N weeks then flip? Lean run-once
   scrub — the existing offenders are a small list (`spec.json`,
   `README.md`, `scripts/`) and we know what they are.
3. **Does the same allowlist apply to draft bundles?** Probably yes —
   drafts are deployable, so the contract should match. But the
   authoring AI may temporarily upload work-in-progress files; the
   answer probably involves a "draft has soft rejection, live has hard"
   policy. Punt to v1.

## 7. Status

Captured as a TODO. Promote to implementation when scheduled.
