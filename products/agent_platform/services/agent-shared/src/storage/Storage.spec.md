# Storage

Content-addressed bundle storage for agent revisions — the file-tree layer
backing `AgentRevision.bundle_uri`. `S3BundleStore` is the prod backend
(SeaweedFS locally); a draft's bundle is a mutable key prefix until `freeze`
stamps a `.frozen` marker and a content hash, after which every write and
delete against that revision id must refuse.

## invariants

- bundle-freeze-immutability

## works when

- typechecks
- boundary "bundle-freeze-immutability" at S3BundleStore
- passes test "freezes and blocks further writes"

## why

bundle-freeze-immutability: `write` and `delete` both check `isFrozen(rev)` before touching S3 and throw `bundle ${rev} is frozen` when the `.frozen` marker object exists; `freeze` writes that marker holding a hash recomputed from each file's actual bytes rather than the writer-supplied `Metadata.sha256` that `list` trusts, so the frozen hash can't be spoofed by an in-cluster writer setting object metadata independently of content. This matters because `agent_revision.bundle_sha256` and every downstream consumer that reads a promoted bundle (the runner at session start, `readTypedBundle`) trust that a given revision id names one immutable set of bytes forever — without the write/delete refusal, a later write to an already-frozen revision id would silently swap content behind a promoted (and possibly already-executing) revision, breaking that promise for anyone who already has the id. `isFrozen` is also the authoritative cross-process signal ahead of `agent_revision.state` (Django stamps `state` _after_ the janitor returns), so the guard can't be raced by an in-flight promote reading a stale `draft` state. The oracle runs against a real S3-compatible backend (SeaweedFS): write, freeze, attempt a second write, assert it throws.
