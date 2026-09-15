---
name: flox-debug
description: >-
  Use when a Flox environment does not resolve the packages
  you expect. Symptoms: `flox install` or `flox upgrade`
  gives a different version than `flox show` lists as
  available; a newly published package does not show up;
  adding one package makes a working environment fail with
  "constraints for group 'toplevel' are too tight"; a
  package resolves on one machine but not on another
  platform or in CI.
---

# Flox Debugging

Debug a Flox environment when it doesn't behave as
expected. Its current coverage is catalog resolution: why
the resolver picks (or skips) specific package builds, and
why adding packages to an existing environment can fail
with constraint errors.

**Resolution failures are usually page problems, not
version-conflict problems.** The reflex is to read
`constraints_too_tight` as two packages wanting
incompatible versions of a shared dependency. That is
almost never what it means here — `constraints_too_tight`
is the generic group-level failure and names no cause by
itself. The cause is one of three things:

- **Page coverage** — no single base page carries every
  package in the group. The most common.
- **Metadata and licence exclusions** — `allow.unfree`,
  `allow.broken` or `allow.licenses` ruled a package out
  on every page.
- **Version conflicts** — a genuine clash between version
  constraints. The least common; reach for it last.

Do the page analysis first, check the `[options]`
exclusions second, and fall back to version-conflict
reasoning only once both rule it out.

## Establish Context

Work it out yourself first. Ask only for what you cannot
determine, and never open with a questionnaire.

1. **Find the environment.** Look for
   `.flox/env/manifest.toml` in the current directory,
   then in any directory the user named. If there is no
   manifest anywhere, you are debugging a standalone
   package — say so and carry on.

2. **Identify the package group.** Read it from the
   manifest: packages with no explicit `pkg-group` are in
   the implicit group, which Flox calls `toplevel` — its
   error messages say `constraints for group 'toplevel'
   are too tight`. If the manifest declares more than one
   group, take the one containing the package the user is
   complaining about and say which you picked. Every
   package in a group must resolve to the same base page,
   so the group scopes the whole diagnosis.

3. **Identify the packages involved.** Take the installed
   set from the manifest. Only a package the user is
   *adding* may need asking, and only if their message
   did not already name it.

Produce the diagnosis from what you can read, and state
the assumptions you made. A user corrects a wrong
assumption faster than they answer three questions.

## Parse the Manifest

Read the `manifest.toml` from the environment. Extract
all packages in the target package group:

```toml
# Example manifest entries:
[install]
gh.pkg-path = "gh"                        # default group
python3.pkg-path = "python3"              # default group
claude-code.pkg-path = "flox/claude-code"
claude-code.pkg-group = "claude-code"     # separate group
nodejs_22.pkg-path = "nodejs_22"
nodejs_22.version = "22.14.0"
nodejs_22.pkg-group = "nodejs"            # separate group
```

For each package in the target group, build a
PackageDescriptor:
- `install_id`: the TOML key (e.g., `gh`, `python3`)
- `attr_path`: the `pkg-path` value
- `systems`: the environment's declared systems, **not**
  the local platform. Read `[options] systems` from the
  manifest. If a package carries its own `.systems`, use
  that list for that descriptor instead. If `[options]
  systems` is absent the environment targets the DEFAULT
  set — which as of Flox 1.15 is three systems
  (`aarch64-darwin`, `aarch64-linux`, `x86_64-linux`);
  `x86_64-darwin` is only targeted when declared
  explicitly — confirm against `manifest.lock`, where
  every locked package records its `system`.
- `version`: the `version` value if present, null
  otherwise
- Skip packages with a `flake` attribute — those are
  not resolved through the catalog

**Never narrow `systems` to your own machine.** Two of
the message types below —
`attr_path_not_found.systems_not_on_same_page` and
`attr_path_not_found.not_found_for_all_systems` — are
multi-system failures by definition. A single-system
reproduction resolves cleanly against the very failure
you were asked to debug, and you will report "works
fine" on a broken environment. This is about the fidelity
of the request, not about how to read the response — see
Step 2 before treating any `attr_path_not_found` as
evidence.

Then apply the environment's `[options]` to **every**
descriptor in the group. These change what resolves, so a
reproduction that omits them is not a reproduction:

| Manifest `[options]` | Descriptor field |
|---|---|
| `allow.unfree = true` | `allow_unfree: true` |
| `allow.unfree = false` | `allow_unfree: false` |
| `allow.broken = true` | `allow_broken: true` |
| `allow.broken = false` | `allow_broken: false` |
| `allow.licenses = ["MIT", …]` | `allowed_licenses: ["MIT", …]` |

Send the false rows too. **`allow_unfree` defaults to
`true` in the API, so omitting it is not neutral** — it
silently grants what the manifest denied. Verified with
one descriptor twice: field omitted resolves cleanly on
page 1017464; `allow_unfree: false` returns `page: null`
with an `error`-level `unfree` message. Skip that row and
a genuinely failing install becomes a clean reproduction.

`allow_broken` defaults to `false` and `allowed_licenses`
defaults to unset (no restriction), so those two are safe
to leave out when the manifest does not set them.
`allow_unfree` is the only inverted default.

`unfree`, `broken` and `licenses` are the only keys
`[options].allow` accepts. The API also accepts
`allow_insecure`, `allow_pre_releases` and
`allow_missing_builds` on a descriptor, but no manifest
key sets them — leave them at their defaults when
reproducing an environment.

The `unfree` and `broken` message types below are exactly
what those two boolean flags gate (`insecure` is the same
shape, gated by `allow_insecure`, which no manifest key
sets). `allow.licenses` behaves differently: a package
excluded by `allowed_licenses` is reported at `trace` as
`resolution_logic` — e.g. `TRACE (hello): The license
GPL-3.0-or-later is not in the allowed licenses:
['MIT'].` — and **not** as an `unacceptable_licenses`
message. See Step 3 for why that matters.

Then append the user's new packages as additional
descriptors in the same group.

## Core Concepts

### Two Kinds of Page

Every resolved package sits at the intersection of two
axes:

- **Base page** — the nixpkgs revision the package was
  built against. This is the `page` number in the API
  response. Higher = newer nixpkgs.
- **Build page** — the source repository revision. This
  is `rev_count` / `rev` / `rev_date` in the response.
  Higher rev_count = newer source.

**The resolver picks the highest base page where ALL
packages in the group can be satisfied.** A newer build
(high rev_count) on an old base page can drag the entire
group down — or make resolution impossible if no single
base page has all packages.

### Why This Causes Confusion

**Scenario 1: New publish not picked up.**
A user publishes a new version. The publish succeeds. But
`flox install` still picks the old build because the new
build was evaluated against an old nixpkgs pin (low base
page), while an older build on a newer base page wins.

**Scenario 2: Adding a package breaks the group.**
User has an environment with packages A, B, C all
resolving on base page 950000. They try to add package D,
which only exists on base page 780000. No single base
page has all four packages, so resolution fails with
`constraints_too_tight`.

## Authentication

```bash
TOKEN=$(flox auth token)
```

Use as `Authorization: Bearer $TOKEN` header on all
catalog API calls.

**Keep the token in the variable.** Never echo it, never
paste it into a command you show the user, and never let
it reach the diagnostic table or the final report. Refer
to it only as `$TOKEN`.

## Diagnostic Flow

### Step 1: Resolve with Candidate Pages

Call the resolve endpoint with the full set of packages
(existing + new) requesting candidate pages:

```bash
curl -s -X POST \
  "https://api.flox.dev/catalog/api/v1/catalog/resolve\
?candidate_pages=10" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [{
      "name": "<GROUP_NAME>",
      "descriptors": [
        {
          "install_id": "<ID>",
          "attr_path": "<PATH>",
          "systems": ["<SYSTEM_1>", "<SYSTEM_2>", "..."],
          "version": "<VERSION_OR_NULL>"
        }
      ]
    }]
  }'
```

**Parameters:**
- `name`: The package group name. For packages with no
  explicit `pkg-group` this is `toplevel`.
- `descriptors`: One entry per package in the group
  (existing from manifest + new from user)
- `systems`: the environment's declared systems, exactly
  as built in "Parse the Manifest" above — never the
  local platform. List every one of them. A request
  carrying a single system is the commonest way to get a
  clean result for an environment that is genuinely
  broken.
- `candidate_pages=10`: Start with 10; increase if
  needed to see more history

### Step 2: Build the Diagnostic Table

From the response, extract the selected page and all
candidate pages. For each page, show each package's
status. Present a table:

| Base page | Complete | Package | Version | Build rev | Build date | Messages |
|-----------|----------|---------|---------|-----------|------------|----------|

Sort by base page descending (highest first = winner).

Fill `Complete` from each page's `complete` field.
**`complete` is a property of your request, not of the
page.** It is `true` when every descriptor you sent
resolved on that page for every system you asked for.
The same page flips with the request: 1027867 is
`complete: true` for `hello` alone and `false` once
`flox/claude-code` joins the group; 1017464 is `true`
for `flox/claude-code` alone and `false` for that same
descriptor with `allow_unfree: false`.

It therefore restates the page's own `messages` array.
Across 12 probes and 126 candidate pages the
correspondence was exact, with no exceptions: 39
complete pages carried zero messages, 87 incomplete
pages carried at least one, and every selected page was
complete. The resolver picks the highest page where it
is `true` — which is the "highest base page satisfying
every package" rule, restated per page.

So the column is worth showing, but it is **not** a
freshness or health signal, and `complete: false` is
never grounds for discarding a page's messages — those
messages are the reason it is `false`.

**Candidate-page messages say why each page was not
selected. They are not, by themselves, the diagnosis.**
They arrive at `error` level on successful resolves too:
`hello` + `flox/claude-code` resolves cleanly on page
1017464 while carrying 50 error-level messages across
its ten candidate pages. Read them for what *differs*
from a run that succeeds, never as a verdict on their
own. The verdict comes from three places:

- `page` — null means the group failed.
- the group-level `messages` array on the item, beside
  `page` and `candidate_pages` rather than inside a
  page. Empty on all five successful probes run for this
  skill; on all five failing ones it carried at least
  one `error` plus three `trace` `resolution_logic`
  "Stage 1/2/3" lines.
- Step 5 — resolving subsets to find which constraint
  actually moves the outcome.

**Read `attr_path_not_found` by `context.valid_systems`,
not by the page's `complete` flag.** Both readings arrive
at `error` level with the same type:

- `valid_systems` empty (`""`) — the attr_path is absent
  from that page entirely. The text mirrors it: `The
  attr_path 'X' is not found.`
- `valid_systems` populated (e.g.
  `"aarch64-darwin,aarch64-linux,x86_64-linux"`) — the
  package is on the page, but not built for every system
  you asked for. Text: `The package 'X' is not found for
  some systems, valid systems are (…)`.

The field is the rule; the text is there so raw output
stays readable by eye. Neither reading is by itself a
failure — the *successful* `hello` + `flox/claude-code`
resolve carries 40 of the first kind and 10 of the
second.

**Worked example — identical messages on success and on
failure.** All four systems, `candidate_pages=10`:

```
hello + flox/claude-code       -> page 1017464, SUCCEEDS
  group messages:     none
  candidate messages: 40 attr_path_not_found naming
                      flox/claude-code (valid_systems
                      ""), 10 naming hello (populated)

hello@2.10 + flox/claude-code  -> page null, FAILS
  group messages:     error constraints_too_tight,
                      3 trace resolution_logic
  candidate messages: the same 50, plus 30
                      version_not_found ("Version 2.12.3
                      does not satisfy the requested
                      version 2.10.")
```

The 40 messages naming `flox/claude-code` are identical
on the run that succeeds and the run that fails, so they
cannot be evidence for the failure. Diagnose from them
and you name `flox/claude-code` as the outlier and tell
the user to move it to its own group — the wrong package
and the wrong fix. What actually changed is the pin:
`hello@2.10` resolves alone on page **348581**, while
`flox/claude-code` sits between 935279 and 1017464, so
no base page carries both.

Do not promote `version_not_found` to a failure signal
either — `hello@2.10` *alone* succeeds on 348581 while
carrying those same 30. It is a difference between the
two runs, not a cause. Step 5 is what turns a difference
into a cause.

Mark the selected page. For candidate pages, show any
messages explaining why they weren't selected or why
specific packages couldn't be satisfied on that page.

Step 4 narrows the question; Step 5 settles it.

### Step 3: Analyze the Gap

Check for these patterns:

**No common base page (constraints_too_tight):**
If `page` comes back null, the packages in the group may
not share a common base page. Identify the outlier by
resolving subsets — Step 5 — not from the candidate-page
messages, which name packages on successful resolves too.
The outlier is the package whose own page range sits
clear of everyone else's. This is the most common issue
when adding a new package to an existing environment.

Confirm it before concluding it. A licence or metadata
exclusion produces the same generic
`constraints_too_tight`, so read the `resolution_logic`
lines first — see the level rule below.

**Stale base page on newest build:**
If the newest build (highest rev_count) has a lower base
page than older builds, the source repo's nixpkgs input
is pinned to an old revision. The fix is to update the
nixpkgs flake input in the source repo and republish.

**Messages explain rejection:**
If candidate pages have messages, report them. Common
message types:
- `constraints_too_tight` — the generic group-level
  failure ("Resolution constraints are too tight."). It
  says the group could not be resolved and nothing more;
  by itself it names no cause
- `missing_builds` — package exists but not for the
  requested system
- `broken` / `insecure` / `unfree` — package metadata
  flags exclude it
- `unacceptable_licenses` — a real value in the API's
  `MessageType` enum, but do not wait for it: a licence
  restriction is reported as `resolution_logic` in
  practice, not as this type. A probe that failed purely
  on `allowed_licenses` produced zero of these across the
  whole response
- `version_not_found` — version constraint doesn't match
- `change_in_version_format` — the version string's
  format changed between builds
- `attr_path_not_found` — package doesn't exist on that
  page, but read `context.valid_systems` before
  believing it: the two readings split as Step 2 sets
  out, and both turn up on successful resolves
- `attr_path_not_found.not_in_catalog` — the attr_path is
  not in this catalog at all
- `attr_path_not_found.systems_not_on_same_page` —
  package exists but not for all requested systems on
  this page
- `attr_path_not_found.not_found_for_all_systems` —
  package not available for some requested systems
- `resolution_logic` — the per-package reason a candidate
  page rejected a package, e.g. the licence it carries
  versus the licences you allowed. **This is usually
  where the real cause lives**, despite arriving at
  `trace` level
- `general` — resolver commentary rather than a specific
  exclusion

Every message carries a **level** — `trace`, `info`,
`warning` or `error`. **Use level to rank, never to
discard.** The catalog reports the *specific* per-package
exclusion reason at `trace` level, typed
`resolution_logic`, while the only `error` is frequently
the generic `constraints_too_tight`. When the sole
error-level message is a generic `constraints_too_tight`,
the diagnosis is in the `trace` lines — read them.

Measured against the live API. A group failing purely on
a licence restriction (`allowed_licenses: ["MIT"]`,
package `hello`, GPL-3.0-or-later, all four systems,
`candidate_pages=10`) returned:

```
('trace', 'resolution_logic')       33
('error', 'constraints_too_tight')   1
('error', 'attr_path_not_found')    10
unacceptable_licenses present?    False
```

The 33 `trace` lines were the *only* messages naming the
cause — a representative one reads `TRACE (hello): The
license GPL-3.0-or-later is not in the allowed licenses:
['MIT'].` Three of them sit at group level and 30 on the
candidate pages, so this is the case where candidate-page
messages *do* carry the cause: a clean `hello` resolve
carries zero `resolution_logic` lines, which is exactly
the "what differs from a run that succeeds" test Step 2
asks for. The single `constraints_too_tight` was generic,
and all ten `attr_path_not_found` errors carried a
populated `context.valid_systems` — the "not found for
some systems" kind, red herrings by the Step 2 field
test. Filter that response down to `error` level and you
are left with one generic failure plus ten "not found
for some systems" rows — you would confidently diagnose
a system-coverage problem for what is a licence
restriction.

Keep this tally here when editing this section. It is the
evidence against re-simplifying the rule back into a
level filter.

Pages also carry `complete`, as recorded in the Step 2
table. It restates that page's own `messages` array for
the request you sent, so it is never independent
evidence, and `complete: false` is never a reason to
discard a page's messages. Read `attr_path_not_found` by
`context.valid_systems` exactly as Step 2 sets out — and
remember what Step 2 measured about both readings: they
turn up on successful resolves too, so neither one names
the outlier by itself. To name the outlier, resolve
subsets — Step 5.

**No messages, just page ordering:**
If all candidate pages have empty messages and the only
difference is base page number, the issue is purely
which nixpkgs base the builds landed on.

### Step 4: Check Individual Package Builds

To see all known builds of a specific package:

```bash
curl -s \
  "https://api.flox.dev/catalog/api/v1/catalog/\
packages/<ATTR_PATH>?page=0&pageSize=50" \
  -H "Authorization: Bearer $TOKEN"
```

This shows `total_count` and individual builds, each
carrying `system`, `version` and `rev_count` — but **no
base page**. So use it to answer a narrower question:
"is this attr_path in the catalog at all, and for which
systems?" A 404 means it is not in the catalog; builds
covering your systems mean any per-page absence is
page-scoped, not a missing package. That is all Steps 2
and 3 send you here for — Step 4 narrows, Step 5
settles.

To find which base page a package actually lands on,
resolve it alone — Step 5.

### Step 5: Isolate the Constraint

Resolve subsets to find which constraint actually moves
the outcome. This is the step that settles a diagnosis;
everything earlier only proposes one.

1. Resolve just the existing packages, without the new
   ones. If that already fails, the new package is not
   the cause. If it succeeds, note the page it lands on
   — an absurdly old page for the existing set is itself
   the finding, and names the constraint dragging the
   group down. In the Step 2 example, `hello@2.10` alone
   resolves on page 348581.
2. Resolve just the new package alone — this shows the
   base pages it is available on. `flox/claude-code`
   alone resolves on 1017464, with candidate pages
   running down to 935279.
3. Compare. No overlap between the two page ranges
   explains the failure, and the package on the far
   older range is the one to fix — relax its version
   pin, republish it against a newer nixpkgs, or move it
   to its own group.
4. If both subsets resolve on overlapping pages, page
   coverage is not the cause. Go back to the `[options]`
   exclusions and the `resolution_logic` traces.

## Presenting Results

Always present findings as:

1. **What resolved** (or failed): The selected page with
   package details, or the error
2. **Candidate table**: All candidates sorted by base
   page descending, with per-package status
3. **Diagnosis**: Why the selected page won, or why
   resolution failed — identify the specific package(s)
   causing the constraint
4. **Action items**: What the user should do:
   - Update nixpkgs input in source repo and republish
   - Adjust version constraints
   - Move a package to a separate pkg-group
   - Check system coverage
   - Wait for the catalog to index a newer build

## Multiple Packages / Package Groups

When debugging resolution with multiple packages in the
same group, remember that all packages in a group must
resolve to the **same base page**. A single package
pinned to an old base page can drag the entire group
down. Check each package's candidate pages independently
to find the constraint.

## Re-running After Changes

After the user publishes a new build or updates their
nixpkgs pin, re-run the resolve call to verify the fix.
Compare the new results to the previous diagnostic table
to confirm the base page moved as expected.
