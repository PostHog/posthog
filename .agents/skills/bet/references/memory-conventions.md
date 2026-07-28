# Memory repo conventions

The `/bet` skill's memory choreography (`memory-seed.sh`, `memory-verdict.sh`)
implements the conventions documented in each product's own memory repo
README — read that README when in doubt, this is a summary, not the source
of truth. It was written against `$MEMORY_GIT_BASE/foundry.git`'s own README,
which (fittingly) documents Foundry's own memory as the reference example.

- **`main` is consensus.** Only a verdict moves it. Everything else lives on
  a bet branch until the market decides.
- **One concept per page** under `pages/`, written as what's true _now_
  (git history is the changelog — `git log -p` / `git blame` on a page shows
  which bet taught which line). The skill does not touch `pages/` directly;
  that's for humans/agents doing knowledge curation, not the bet lifecycle.
- **`bets/<slug>.md`** is the run record of one bet — hypothesis, what was
  built, what was learned, the verdict. `memory-seed.sh` creates this file
  from the bet spec; `memory-verdict.sh` is the only thing that edits the
  `**Verdict**:` line, and does so _before_ any merge/tag, so the verdict
  travels with whatever the git choreography does next.
- **Branch per bet**: `bet/<slug>`, created from `main`. This is what a
  managed bet's `memory_repo_url` points sandboxes at.
- **Merge on verdict**:
  - `promoted` → `git merge --no-ff bet/<slug>` into `main`. Knowledge becomes
    consensus at the same moment the market accepts the work.
  - `rolled_back` → tag `archive/<slug>` at the branch tip (kept, not
    deleted), then extract just `bets/<slug>.md` onto `main` (`git checkout
bet/<slug> -- bets/<slug>.md` there) so the failure's learning entry
    lands on consensus without dragging in whatever else changed on the
    branch. Failed bets teach the most; dead designs stay off `main`.
  - `iterate` → branch stays untouched for the next round.
- **Merge conflicts are signal, not friction**: two concurrent bets editing
  the same page hold genuinely divergent understanding. This skill's scripts
  don't attempt automatic conflict resolution for `pages/` — if a promote or
  rollback ever produces one there, resolve it by hand with both verdicts in
  hand, and note in the resolution commit which claim won and why. The
  scripts only ever touch `bets/<slug>.md` and `map.md`, which are
  slug-scoped and rarely conflict.
- **`map.md`** indexes every page and bet with `[[wikilinks]]`.
  `memory-seed.sh`/`memory-verdict.sh` append a one-line entry
  (`- [[slug]] — hypothesis`) if one isn't already there — never rewrite
  existing lines.

## Local clone cache

Scripts keep a local clone at `~/.cache/foundry-bet/memory-<product>/`
(override with `MEMORY_CACHE_DIR`) rather than re-cloning on every call.
Every invocation fetches `origin` and resets to it before doing anything, so
a stale local cache never silently diverges from the real remote.
