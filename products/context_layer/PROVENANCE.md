# Per-page provenance

Design for gating wiki reads on project access.
Nothing here is built yet: the wiki is readable by anyone in the organization (see the README's "Who can read it").

## Why not a simpler gate

The obvious first idea is one audience for the whole wiki: reading takes access to every project feeding it.
That is safe and it is small, but it is coarse in two ways a user runs into immediately.

One restricted project shrinks the whole wiki's audience to that project's members.
And a project can never be removed from the set, because content synthesized from it is already spread across `org/`, `areas/`, and `decisions/` pages with nothing recording where it came from.
An "include or exclude projects" control needs removal to mean something, so it needs that record.

Scoping by path does not work either, for the same reason: a derived claim lands in an organization-wide page even when its only source is one project.

## The page contract

Two frontmatter fields carry it.

`sources` becomes a list of typed references rather than free text:

```markdown
---
summary: How activation is measured.
status: active
sources: task:018f2c…, space:019a77…, project:2
visibility: project:2
---
```

`visibility` is the set of projects a reader must be able to open to read the page.
The server owns it, the way it owns `index.md` and `scripts/`: it computes the value at land time and the linter rejects a page whose author set it.

A page's visibility is the union of the projects its sources resolve to.
Union, not intersection: a page carrying a fact from project 2 and a fact from project 7 discloses both, so reading it takes access to both.

## Where each check lives

`repo_lint.py` is stdlib-only because it ships into every wiki as `scripts/lint`, so an agent runs the same rules the server enforces.
It has no database, so it cannot resolve a reference to a project.
The split follows from that:

| Check                                                            | Runs in                               |
| ---------------------------------------------------------------- | ------------------------------------- |
| `sources` is present and every entry parses as a typed reference | `scripts/lint`, and again server-side |
| `visibility` is absent or unchanged from what the server wrote   | `scripts/lint`, and again server-side |
| Each reference resolves to something real, in this organization  | server only, at land                  |
| `visibility` recomputed and stamped                              | server only, at land                  |

## Reference kinds

| Reference                | Resolves through              | Projects     |
| ------------------------ | ----------------------------- | ------------ |
| `project:<id>`           | itself                        | that project |
| `space:<uuid>`           | the channel's team            | that project |
| `task:<uuid>`            | the task's team               | that project |
| `loop:<uuid>`            | the loop's team               | that project |
| `event:<team_id>:<name>` | the definition's team         | that project |
| `scaffold`               | nothing; server-written pages | none         |

A reference the server cannot resolve fails the land.
Defaulting an unresolved reference to "no projects" would make every typo an organization-wide page, which is the leak this design exists to close.

Pull requests are deliberately absent.
A repository does not belong to a project, so a PR only attributes through the task that produced it, and a dream citing a PR cites that task instead.

## Reading

An API read filters the tree and each page against the caller's readable projects.
The filter is per page, so there is no wiki-level audience left: someone who can open project 2 but not project 7 sees every page drawing only on project 2, and the rest is not listed.

A sandbox mount cannot filter that way, because it hands over a git bundle.
It gets a filtered bundle instead: a checkout with the unreadable pages removed, committed as a single commit and cached in object storage under `(head_sha, access key)`, where the access key is a hash of the sorted readable project ids.
Most runs in an organization share one access key, so the cache is warm after the first.

Squashing costs the sandbox its history, which the dreaming skill reads (`git log --merges -10`).
So the dream keeps the full bundle.
It is dispatched by the server rather than by a person, and it already runs as a user who must be able to read everything, which the dispatch check enforces.

## Landing

A filtered clone's history diverges from the wiki's, so commits made in one cannot be rebased onto it.
Runs with a filtered mount therefore write through the page endpoint, which takes a path, content, and a base head, and is already how a loop run writes.
Bundle landing stays with the dream, which is the only writer holding a full clone.

## Excluding a project

Once slices 1 to 3 exist, a project can be excluded. Excluding stops it feeding the wiki, and then:

- A page whose visibility is only that project is deleted.
- A page that also draws on projects still included keeps its visibility, so it stays readable to exactly the people who could read it before. It is queued for the consolidation pass, which either rewrites it without the excluded material or removes it.

Nothing widens.
That is the property the whole design is for: no edit to the project set ever makes existing content readable to someone who could not read it a moment earlier.

## Migrating an existing wiki

Existing pages have free-text sources and no visibility, and every one of them is readable by the whole organization today.
Stamping them all as organization-wide preserves that exactly, and it is the only honest starting point: nothing in the repository records which project a sentence came from, so there is no backfill anyone can compute.
Dreams re-stamp pages as they rewrite them, so provenance sharpens from the day it ships rather than arriving complete.

Turning this on therefore hides nothing retroactively.
It stops new content leaking, and the old content ages out as the wiki is rewritten.

## Landing order

Each slice is useful on its own and safe to deploy alone.

1. **Record provenance.** Typed sources, server-stamped visibility, lint rules, skill and scaffold updates, the migration stamp. Nothing reads visibility yet, so this changes no behavior.
2. **Filter reads.** The tree, page, report, and channel-page endpoints filter per page. This is the slice that stops the wiki being organization-wide.
3. **Filter mounts.** Filtered bundles with the access-key cache, and bundle landing restricted to full-clone runs.
4. **Edit the set.** The include/exclude UI, the exclusion rules above, and the consolidation queue for pages that outlive an excluded project.
