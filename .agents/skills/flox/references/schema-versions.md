# Manifest Schema Versions

Depth behind the *Manifest schema versions* block in SKILL.md's Quick
Reference. That block is enough to write a correct manifest; read this when
you need to explain *why* a version line is what it is, when a user asks what
migration will and won't do for them, or when you are choosing between
`schema-version` and `minimum-cli-version`.

## The two keys

Every manifest declares which schema it follows, on the very first key:

```toml
version = 1                   # legacy form: any flox CLI
```
```toml
schema-version = "1.12.0"     # modern form: needs flox >= 1.12.0
```

**The two keys are mutually exclusive**, which is why they are shown above as
two separate manifests. A manifest carrying both is rejected; bumping a schema
means *replacing* the `version = 1` line, not adding to it.

## A schema version is a minimum CLI version

The value is literally a flox release number, and it names the oldest CLI that
can read the environment. `schema-version = "1.13.0"` works on flox 1.13.0 and
everything newer; on flox 1.12.x it fails immediately with `manifest had
invalid schema version '1.13.0'`. That is the whole point of the field — it
lets an environment say "you need at least this much flox" before anything
else is attempted.

Only releases that actually changed the schema get a version, so the valid
values are a short list, not every flox release:

| Schema | Introduced in | What it gates |
|--------|---------------|---------------|
| `version = 1` | before 1.10.0 | the original schema — gates nothing, and every flox still accepts it |
| `"1.10.0"` | flox 1.10.0 | package `outputs` selection in `[install]`; `minimum-cli-version` in its plain-string form |
| `"1.11.0"` | flox 1.11.0 | the `minimum-cli-version` table form (`{ version, reason }`) |
| `"1.12.0"` | flox 1.12.0 | `[services] auto-start` |
| `"1.13.0"` | flox 1.13.0 | `[profile] deactivate`; build `sandbox = "warn" \| "enforce"` and `sandbox-allow` |
| `"1.14.0"` | flox 1.14.0 | `[plugins.<pkg-name>]` tables (experimental) |

## New environments get the CLI's newest schema

`flox init` writes the latest value the installed CLI knows — flox 1.13.2
writes `schema-version = "1.13.0"` (the newest *schema*, which is why a patch
release still writes `.0`). This, not migration, is why a manifest you open is
often already new enough for the field you want: it was created that way.

## Forward migration: only when the operation needs it

The rule is not "every command upgrades the file" and not "nothing ever
upgrades it". When flox writes an environment it first tries to express the
result in the schema the file already declares, and rewrites the version line
**only if the result no longer fits there** — so an environment is not forced
onto a newer flox for everyone else without cause.

"Writes the environment" is broader than "edits the manifest": writing
`manifest.lock` is a mutation too, and the schema check runs on the locking
path. So an ordinary `flox activate` can bump the version line, with no
manifest edit anywhere, if activation had to re-lock.

Reproduced on flox 1.13.2, starting from a `version = 1` manifest each time:

| starting point | command | first line afterwards |
|---|---|---|
| `hello`, lock present | `flox install hello`, `flox list`, `flox activate` | `version = 1` |
| `bash`, lock present | `flox activate`, `flox list` | `schema-version = "1.13.0"` |
| any package, lock missing or stale | anything that locks | `schema-version = "1.13.0"` |

The difference between the first two rows is the package, not the command.
`hello` has one output; `bash` ships `dev doc info man out` but installs only
`man out` by default. Under `version = 1` there was no per-package `outputs`
field and flox installed *all* of a package's outputs; schema `1.10.0`
introduced `outputs` and changed the default to only the package's *default*
outputs. So to keep behavior identical, migrating writes `outputs = "all"` on
exactly those packages whose available outputs differ from what they install
by default — and `version = 1` has no way to express that field, so those
manifests get a new version line. Packages like `hello`, where the two sets
match, need no `outputs` field, round-trip cleanly, and keep `version = 1`.

The third row is the same rule with less information: with no usable lock,
flox cannot prove which case a package is in, so it assumes all outputs and
migrates.

Two consequences worth knowing: when flox does migrate it goes straight to the
CLI's **newest** schema, not the oldest one that would have sufficed (the
`outputs` above only needs `"1.10.0"`, but the file lands on `"1.13.0"`); and
it never *lowers* a version line, so a manifest already above what it needs
stays where it is.

The practical takeaway for anything you write: **don't reason about whether
migration has happened — read the first line of the file.**

## None of that will rescue a hand-edit

Parsing happens before migration. If you add a newer field with an editor or
`sed` and leave the old version line in place, flox rejects the file outright —
there is no half-way state in which the migration logic gets a look at it. So
when *you* write the field, you must raise the version line **in the same
edit**. Read the first line before you touch anything: raise it if it is below
what the field needs, and leave an already-higher `schema-version` alone.

**Getting it wrong is a parse error, not a silent no-op** — the schema is
enforced with `deny_unknown_fields`, so an unknown or mistyped key is rejected
rather than ignored. The message names the field, not the schema, which makes
it easy to misread as "this key doesn't exist" when the real fix is a version
bump:

- `auto-start = true` under `version = 1` →
  ``invalid type: boolean `true`, expected struct ServiceDescriptor in `services.auto-start` ``
- `sandbox = "warn"` under `version = 1` →
  ``unknown variant `warn`, expected `off` or `pure` in `build.<name>.sandbox` ``

If a key you know exists is rejected, check the manifest's schema version
before concluding the key is wrong.

## `minimum-cli-version` is a separate, softer knob

It needs *some* `schema-version` — under `version = 1` it is an unknown field —
but the plain string form already works at `"1.10.0"`; only the
table-with-`reason` form below needs `"1.11.0"` or newer (at `"1.10.0"` it
fails with ``invalid type: map, expected a string``). Don't raise the schema
further than you have to: every bump raises the required flox version for
everyone sharing the environment. Use it to ask for a *higher* CLI than the
schema alone implies — typically a bugfix release, where nothing about the
manifest's shape changed. The difference matters: a too-old `schema-version`
is a hard parse failure, whereas a too-old `minimum-cli-version` only emits a
warning and the command still runs. It takes a bare semver string or a table
with a reason:

```toml
schema-version = "1.11.0"
minimum-cli-version = { version = "1.12.1", reason = "needs the service restart fix" }
```
