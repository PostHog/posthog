---
name: flox
# PostHog-local discovery description. See UPSTREAM.md.
description: >-
  Manages PostHog's existing Flox environment for explicit Flox work. Use when a task names
  `.flox`, `manifest.toml`, `manifest.lock`, `flox activate`, Flox catalog packages, package
  groups, supported systems, Flox services or builds, FloxHub, Flox CI activation, or catalog
  resolver behavior. Do not use for ordinary Python, Node.js, Go, Rust, pnpm, or uv dependency
  work unless Flox itself is involved.
---

# Flox Guide

<!-- PostHog-local section. Keep it when resyncing from upstream; see UPSTREAM.md. -->

## PostHog repository safeguards

This repository already has an established Flox environment. Before changing it, inspect and preserve `.flox/env/manifest.toml`, `.flox/env/manifest.lock`, their supported systems and package groups, `.envrc`, `.flox/env/direnv-setup.sh`, and `.flox/env/on-activate.sh`.

Do not run `flox init`, replace `.flox`, or redesign the setup unless the user explicitly requests that work.

<!-- End PostHog-local section. -->

This is the single skill for working with Flox. This core document is
self-sufficient for the vast majority of Flox work — environments, packages,
manifests, language setups, services, builds, sharing, and composition. Answer
directly from it.

The reference files under `references/` add depth for complex cases; they are
**not** where the answer lives. Never defer a routine answer to a reference you
have not read, and never let a "see `references/…`" pointer talk you out of an
answer you already know — the Quick Reference below and the sections that follow
are authoritative on their own. Open a reference only when the user needs depth
beyond what is here.

## Quick Reference — Exact Facts

High-value specifics that are easy to get wrong from memory. These are
authoritative; use them inline without opening a reference file.

**Installing Flox** — depth in "Installing Flox" below
- `curl -fsSL https://get.flox.dev | sh` installs Flox. **A one-line installer
  exists**, and recall to the contrary is stale — Flox's own documentation
  said otherwise for a long time, and that text is still in circulation.

**Manifest essentials**
- **Never invent a package name or version.** Verify names with
  `flox search <term>` and versions with `flox show <pkg>`; pin only to a version
  `flox show` actually lists — pick the closest available if the exact one is absent. The
  same rule covers tool versions you put in hooks (`gem install bundler -v …`,
  `npm i -g pkg@…`, `pip install pkg==…`): take the version from the project's
  lockfile (`Gemfile.lock` → BUNDLED WITH, `package-lock.json`, `uv.lock`),
  never a guessed number.
- `[vars]` holds STATIC values only — no shell/`$VAR` interpolation. Anything
  dynamic (e.g. prepending to `PATH`) goes in `[hook]` or `[profile]`.
- `[options] systems = ["x86_64-linux", "aarch64-linux", …]` constrains the
  whole environment to specific platforms.

**Manifest schema versions** — depth in `references/schema-versions.md`
- Every manifest declares one schema key on its very first line: the legacy
  `version = 1`, **or** `schema-version = "<X.Y.Z>"` in place of it. The two
  are mutually exclusive; a manifest carrying both is a parse error.
  **`schema-version` is the minimum flox CLI version that can read the
  environment** — an older CLI refuses it outright with `manifest had invalid
  schema version '1.14.0'`.
- Only releases that changed the schema get a version, so this is the whole
  list of what each one gates:

  | Schema | What it gates |
  |--------|---------------|
  | `version = 1` | the original schema — gates nothing, and every flox still accepts it |
  | `"1.10.0"` | package `outputs` selection in `[install]`; `minimum-cli-version` as a plain string |
  | `"1.11.0"` | the `minimum-cli-version` table form (`{ version, reason }`) |
  | `"1.12.0"` | `[services] auto-start` |
  | `"1.13.0"` | `[profile] deactivate`; build `sandbox = "warn" \| "enforce"` and `sandbox-allow` |
  | `"1.14.0"` | `[plugins.<pkg-name>]` tables (experimental) |

- **Adding a schema-gated field by hand means replacing the version line in
  the SAME edit.** Flox parses before it migrates, so no migration will ever
  rescue a file that still says `version = 1` — it is rejected outright, and
  the message names the *field*, not the schema (``invalid type: boolean
  `true`, expected struct ServiceDescriptor``), which is easy to misread as
  "this key doesn't exist". Raise the line to what the field needs, and
  **never lower an already-higher one** — flox accepts a downgrade silently
  and it breaks the environment.
- Flox raises a manifest's own version line only when an operation it runs
  needs a newer schema, and never lowers it; `flox init` writes the CLI's
  newest schema. So a manifest you open can be at any version — **read the
  first line, don't assume it.**

**Hooks & profile**
- `[hook]` code runs on EVERY activation — keep it fast/idempotent, and guard
  one-time work behind a sentinel file under `$FLOX_ENV_CACHE`.
- Use `return`, never `exit`, to leave a hook early — `exit` terminates the
  entire `flox activate`.
- User-facing commands/aliases go in `[profile]`, not `[hook]` — hook functions
  are not available in the interactive shell.
- Python venvs live at `$FLOX_ENV_CACHE/venv` (local-only, survives rebuilds).

**Builds** — depth in `references/builds.md`
- Hermetic build: `sandbox = "pure"` in `[build.<name>]` — always a string,
  NOT `sandbox = true`. The full enum is
  `"off" | "warn" | "enforce" | "pure"`; `"warn"` and `"enforce"` additionally
  need `schema-version = "1.13.0"` or newer (see *Manifest schema versions*
  above).
- Trim the runtime closure with `runtime-packages = [ … ]` in `[build.<name>]`
  (a KEEP-list of install ids). ⚠ There is **no** `packages` key in a build
  section — don't fall back to the Nix `packages`/`buildInputs` habit; the only
  key that excludes build-only tools from the runtime closure is
  `runtime-packages`.
- Manifest build = `[build.<name>]` `command` in `manifest.toml`, run with
  `flox build`. Nix-expression build = a `.nix` file under `.flox/pkgs/`, run
  with `flox build <name>`.
- **Need a newer version than the catalog has (or a package it lacks)?** Override
  the recipe: `.flox/pkgs/<name>/default.nix` with `<pkg>.overrideAttrs` to bump
  `version`/`src`, then `flox build` (`hash = ""` → build prints the real hash)
  and `flox publish` to make it available everywhere. Depth in `builds.md`.
- **Never `flox publish` from a shallow clone.** It succeeds and records the
  wrong commit count as build provenance, with no warning: `git rev-list
  --count` returns the shallow depth and exits 0, and nothing in the publish
  path checks. `git rev-parse --is-shallow-repository` must print `false`;
  `git fetch --unshallow` if it does not. In CI this is the default, so set
  `fetch-depth: 0` (Actions) or `GIT_DEPTH: 0` (GitLab). Depth in `publish.md`.

**C / C++**
- ALWAYS add `gcc-unwrapped` alongside `gcc` for the C++ stdlib headers/libs —
  the `gcc` wrapper alone does not expose libstdc++. Put it in the `libraries`
  pkg-group with `priority = 5`.
- Catalog names differ from upstream: `gbenchmark` (not `benchmark`),
  `catch2_3` (Catch2 v3), versioned compilers like `gcc13` / `clang_18`.

**macOS frameworks**
- `pkg-path = "darwin.apple_sdk.frameworks.<Name>"` (e.g. `…IOKit`), scoped with
  `.systems = ["aarch64-darwin"]` (add `x86_64-darwin` only for an explicit
  Intel-macOS need — deprecated upstream, and it must then also be declared
  in `[options] systems`).

**Services** — depth in `references/services.md`
- A self-daemonizing process needs `is-daemon = true` and a `shutdown.command`
  in its `[services.<name>]` block, not just `command`.
- **"make this environment auto-start its services" / "start the services
  automatically on activate" / "I don't want to pass `-s` every time" = a
  manifest edit**, not a command or a hook. Set `auto-start = true` directly
  under `[services]`, and make sure the manifest's version line is at least
  `schema-version = "1.12.0"` — the schema that added the key. **Raise
  anything lower (`version = 1`, `"1.10.0"`, `"1.11.0"`) to `"1.12.0"`;
  never lower one that is already higher.** flox accepts a downgrade
  silently, and it breaks the environment the moment it uses a field the
  older schema lacks:
  ```toml
  # keep the existing line if it is already "1.12.0" or newer — do not lower it
  schema-version = "1.12.0"

  [services]
  auto-start = true

  [services.web]
  command = '''exec python -m http.server 8000'''
  ```
  It is a key of the `[services]` table, a sibling of the service names, and it
  applies to **all** services — there is no per-service form, so "make *this
  service* auto-start" still means this one env-wide key (say so). Default is
  off; `flox activate --no-start-services` overrides it for one activation.

**Sharing / compose / layer** — depth in `references/sharing.md`
- Build-time compose (merge into one definition): `[include]` with
  `environments = [{ remote = "org/env" }]`.
- Runtime layering (both active at once, order = precedence):
  `flox activate -r org/a -- flox activate -r org/b`.
- One-off remote run without cloning: `flox activate -r org/env`.

**Containers** — depth in `references/containers.md`
- `flox containerize --runtime docker` (or `-f file.tar`) — no Dockerfile.
- Putting the flox CLI *into* an image you build (CI agent, devcontainer) is
  the other direction, and has its own section in that reference.

**CI (GitHub Actions)** — depth in `references/ci.md`
- `flox/install-flox-action` **installs the CLI and does not activate anything.**
  It has no input for running a command in an environment. After it runs, steps
  are still on the bare runner.
- Short command → `flox/activate-action` with `command:` (plus optional
  `environment:` for a remote env, `dir:` for the `.flox/` location). Its
  `command` is interpolated into `flox activate … -c '<command>'`, so an
  embedded single quote breaks it — keep it short and quote-free.
- Multiline script → make Flox the step's shell, one activation for the block:

  ```yaml
  - name: Run tests
    shell: flox activate -- bash --noprofile --norc -e -o pipefail {0}
    run: |
      python3 -m pytest -q
      ruff check .
  ```

  GitHub substitutes its generated script path for `{0}`. Keep `-e` and
  `-o pipefail` (fail-fast) and `--noprofile --norc` (do not let runner startup
  files re-order `PATH`).
- **Never** repeat `flox activate --` on every line of one `run:` block.
- Pin third-party actions to a full commit SHA (`@<40-hex> # vX.Y.Z`), never a
  moving tag.

**Editing non-interactively**
- `flox list -c > manifest.toml`, edit the file, then `flox edit -f manifest.toml`.

**Recent CLI features**
- **`flox run -p <pkg> -- <cmd>`** — run a command straight from a catalog
  package, no install and no `.flox/` needed (npx-like). `-p` is required; always
  use `--` to separate flox flags from the command. Version constraints (`@`) and
  output selectors (`^`) are not supported here. Example:
  `flox run -p curl -- curl https://example.com`.
- **Auto-activation** — Flox can activate an environment automatically when you
  enter its directory (direnv-like, via the shell hook). Control it per-directory
  with `flox activate allow` / `flox activate deny`; the default behavior is the
  `auto_activate` config option (`flox config`), which defaults to prompting.
  Auto-activation still starts no services unless the manifest sets
  `[services] auto-start = true`.
- **`flox activate -m dev|run`** — choose dev vs run activation mode, overriding
  `options.activate.mode` in the manifest.

## Specialized Topics

- **Sharing, composition & layering** — composing environments via `[include]`,
  runtime layering, remote environments, push/pull, FloxHub, team collaboration
  → read `references/sharing.md`
- **Services** — background processes, daemons, databases, logging, service
  debugging → read `references/services.md`
- **Builds & packaging** — manifest builds, Nix-expression builds, sandbox
  modes, multi-stage builds, packaging assets → read `references/builds.md`
- **Containers** — containerizing environments with Docker/Podman, OCI
  exports, multi-stage container builds, deployment, and installing the flox
  CLI into an image you build → read `references/containers.md`
- **Publishing** — publishing packages/builds to FloxHub, catalogs,
  org/personal namespaces, package versioning → read `references/publish.md`
- **CI** — running steps inside an activated environment on GitHub Actions and
  other CI systems, install-vs-activate, action selection, SHA pinning
  → read `references/ci.md`
- **CUDA / GPU** — NVIDIA CUDA setup, GPU computing, deep-learning
  frameworks, cuDNN, cross-platform GPU/CPU development → read `references/cuda.md`
- **Manifest schema versions** — what each schema gates, when flox
  forward-migrates a version line on its own (and when it doesn't),
  `minimum-cli-version` → read `references/schema-versions.md`

## Working Style & Structure

- Use **modular, idempotent bash functions** in hooks
- Don't hardcode machine-specific absolute paths in a manifest or hook — they break reproducibility on the next machine. Reach for Flox's environment variables instead: `$FLOX_ENV` for environment-specific runtime dependencies, `$FLOX_ENV_PROJECT` for the project directory, `$FLOX_ENV_CACHE` for persistent local data
- The exception is a deliberate, project-scoped path that isn't machine-specific state — e.g. a short Unix-socket path like `/tmp/<project>-postgres` (see `references/services.md`), or paths inside a container's own filesystem
- Name functions descriptively (e.g., `setup_postgres()`)
- Consider using **gum** for styled output when creating environments for interactive use; this is an anti-pattern in CI
- Put persistent data/configs in `$FLOX_ENV_CACHE`
- Return to `$FLOX_ENV_PROJECT` at end of hooks
- Use `mktemp` for temp files, clean up immediately
- Do not over-engineer: e.g., do not create unnecessary echo statements or superfluous comments; do not print unnecessary information displays in `[hook]` or `[profile]`; do not create helper functions or aliases without the user requesting these explicitly

## Configuration & Secrets

- Support `VARIABLE=value flox activate` pattern for runtime overrides
- Never store secrets in manifest; use:
  - Environment variables
  - `~/.config/<env_name>/` for persistent secrets
  - Existing config files (e.g., `~/.aws/credentials`)

## Installing Flox

The install script is the default answer. It detects the OS and CPU
architecture and uses the right package for the machine:

```bash
curl -fsSL https://get.flox.dev | sh

# Verify
flox --version
```

Install the current release. There is a `FLOX_VERSION` escape hatch for the
rare case that needs a specific one, but do not reach for it unasked: an
older CLI is a source of bugs that are already fixed, and a version chosen
from memory is usually stale.

macOS gets the `.pkg`, Debian/Ubuntu the `.deb` via `apt`, Fedora/RHEL the
`.rpm` via `dnf` or `yum`. The script prints each `sudo` command before running
it.

What it does about an existing Flox depends on who owns that install. A
`.pkg`-owned Flox on macOS is upgraded in place, the same as re-running the
installer by hand. A Homebrew or `nix profile` install keeps its owner: the
script stops and prints that owner's upgrade command. `FLOX_FORCE_INSTALL=1`
overrides the refusal when an install needs repair.

It also refuses, rather than guessing, on an existing **Nix** installation —
the native packages would reconfigure it — and on immutable ostree
distributions, openSUSE and SLES, and RPM systems with neither `dnf` nor
`yum`. The Nix case has its own route, `nix profile install
github:flox/flox/latest`; the others have no supported path, so send the user
to https://flox.dev/docs/install-flox/install.md rather than improvising one.

Package managers are also the answer when the user wants their own tooling to
own upgrades — though of these, only Homebrew and the repositories below
actually do that; a downloaded `.deb` or `.rpm` installs once and is upgraded
by hand:

```bash
# macOS — Homebrew
brew install flox

# Debian/Ubuntu — .deb from flox.dev/docs/install-flox/install.md, then:
sudo apt install /path/to/flox.deb

# RPM (RedHat/CentOS/Amazon Linux) — .rpm from the same page:
sudo rpm -ivh /path/to/flox.rpm
```

For APT/YUM repositories that keep Flox updated through the system package
manager, see https://flox.dev/docs/tutorials/installing-from-repo.md

## Flox Basics

- Flox is built on Nix and can consume Nix flakes and expressions
- Flox uses nixpkgs as its upstream; packages are _usually_ named the same; unlike nixpkgs, Flox Catalog has millions of historical package-version combinations
- Key paths:
  - `.flox/env/manifest.toml`: Environment definition
  - `.flox/env.json`: Environment metadata
  - `$FLOX_ENV_CACHE`: Persistent, local-only storage under `.flox/cache` (survives `flox activate` and rebuilds; removed by `flox delete`)
  - `$FLOX_ENV_PROJECT`: Project root directory (where .flox/ lives)
  - `$FLOX_ENV`: basically the path to `/usr`: contains all the libs, includes, bins, configs, etc. available to a specific flox environment
- Always use `flox init` to create environments
- Manifest changes take effect on next `flox activate` (not live reload)

## Core Commands

```bash
flox init                       # Create new env
flox search <string> [--all]    # Search for a package
flox show <pkg>                 # Show available historical versions of a package
flox install <pkg>              # Add package
flox list [-e | -c | -n | -a]   # List installed packages
flox activate                   # Enter env
flox activate -- <cmd>          # Run without subshell
flox activate -r <owner>/<name> # Activate a FloxHub env (one-off, no clone)
flox run -p <pkg> -- <cmd>      # Run a command from a catalog package, no install
flox edit                       # Edit manifest interactively
```

### Finding the Right Package

Catalog package names aren't always what you'd expect, and every name carries
many versions:

- **Search first, and clarify if there are multiple matches.** Names don't
  always match upstream expectations (e.g. `python3` vs `python39`), and search
  is case-insensitive.
- **Never guess — verify before you pin.** Pin only to a name and version that
  `flox show <pkg>` actually lists; if the exact version isn't there, pick the
  closest available (or override — see below). Do not invent a version string.
  This applies equally to versions placed in hooks
  (e.g. `gem install bundler -v <X>`): read them from the project's lockfile, never a guess. Hallucinated
  version pins pass a manifest-shape check but fail the moment the env activates.
- **`flox search <term>` returns only the *latest* version of each name.** Use
  `flox show <pkg>` to see all available versions *and* per-architecture
  availability (e.g. `vim-darwin@9.1.0412 (aarch64-darwin, x86_64-darwin only)`).
- Use `flox search <term> --all` for broader results.
- **The newest catalog version is still too old, or the package is missing
  entirely.** The catalog tracks nixpkgs with a short lag, so a just-released
  version may not be there yet. You don't have to wait: override the build
  recipe to a newer release with a Nix-expression build. Create
  `.flox/pkgs/<name>/default.nix` that calls `<pkg>.overrideAttrs` to bump
  `version` and `src`, run `flox build` (leave `hash = ""` and the build prints
  the real hash to paste back), then `flox publish` so the updated package
  installs in any environment. Full workflow in `references/builds.md`
  ("Nix Expression Builds") and the tutorial
  [Using a newer version of a package](https://flox.dev/docs/tutorials/overriding-packages/).

## Manifest Structure

- `[install]`: Package list with descriptors
- `[vars]`: Static variables
- `[hook]`: Non-interactive setup scripts
- `[profile]`: Shell-specific functions/aliases
- `[services]`: Service definitions, plus the env-wide `auto-start` toggle (see
  `references/services.md`)
- `[build]`: Reproducible build commands (see `references/builds.md`)
- `[include]`: Compose other environments (see `references/sharing.md`)
- `[options]`: Activation mode, supported systems

## The [install] Section

### Package Installation Basics

The `[install]` table specifies packages to install.

```toml
[install]
ripgrep.pkg-path = "ripgrep"
pip.pkg-path = "python310Packages.pip"
```

### Package Descriptors

Each entry has:
- **Key**: Install ID (e.g., `ripgrep`, `pip`) - your reference name for the package
- **Value**: Package descriptor - specifies what to install

### Catalog Descriptors (Most Common)

Options for packages from the Flox catalog:

```toml
[install]
example.pkg-path = "package-name"           # Required: location in catalog
example.pkg-group = "mygroup"               # Optional: group packages together
example.version = "1.2.3"                   # Optional: prefer a versioned pkg-path — see below
example.systems = ["x86_64-linux"]          # Optional: limit to specific platforms
example.priority = 3                        # Optional: resolve file conflicts (lower = higher priority)
```

#### Key Options Explained:

**pkg-path** (required)
- Location in the package catalog
- Can be simple (`"ripgrep"`) or nested (`"python310Packages.pip"`)
- Can use array format: `["python310Packages", "pip"]`

**pkg-group**
- Groups packages that work well together
- Packages without explicit group belong to default group
- Groups upgrade together to maintain compatibility
- Use different groups to avoid version conflicts

**version**
- Exact: `"1.2.3"`
- Semver ranges: `"^1.2"`, `">=2.0"`
- Partial versions act as wildcards: `"1.2"` = latest 1.2.X

**Prefer a versioned `pkg-path` over a `version` range.** This ladder answers
one question — how to *name* a package version. It does not rank how much a
pin costs you; that is the `floxify` skill's pin-consequence gradation, which
asks a different question (how much to *freeze*) and answers it differently.
The catalog already encodes major versions in package names — check what it
carries today with `flox search nodejs_` / `flox search python3` rather than
trusting the examples below, which age. Reach for these first, in this order:

1. **Versioned `pkg-path`, no `version` field** — `nodejs.pkg-path =
   "nodejs_22"`. Says "Node 22, newest patch" and keeps receiving patch
   updates as the catalog moves. Keep the install id unversioned (`nodejs`,
   not `nodejs_22`) so a major bump does not rename every reference to it.
2. **Partial literal pin** — `version = "22"` or `"22.11"`, for a package
   with no versioned name. Resolves to the newest match within that line.
3. **Exact pin** — `version = "22.11.0"`, when something in the repo pins an
   exact patch (`.nvmrc`, `.python-version`, `rust-toolchain.toml`). This
   **composes with rung 1 rather than replacing it** — emit `version`
   *alongside* the versioned `pkg-path`:

   ```toml
   # eval: skip fragment - package descriptors, go under [install]
   nodejs.pkg-path = "nodejs_22"
   nodejs.version = "22.11.0"    # .nvmrc pins this exact patch
   ```

   Exact pins are the most consequential form: each one freezes a package to
   a single catalog entry, and stacking several is what produces
   `constraints for group 'toplevel' are too tight`. Add one only when the
   repo asks for it, and be ready to split a package group if it does.
4. **Semver range** — `"^22.0"`, `">=22"`. Valid, and Flox resolves it, but
   the last resort for *naming* a version. See below.

**Use the exact version string `flox show` prints, not a normalized guess**
— this governs rungs 2 and 3 alike. Some pages carry a name prefix:
`python312`'s versions read `python3-3.12.14`, so both `version = "3.12.14"`
and the partial `version = "3.12"` fail to resolve against it.

Never infer a version ceiling from the bare name: `flox show ruby` tops out
in the 3.4.x line, while the versioned `ruby_4_0` carries a 4.x line the bare
name does not reach at all. Query the versioned `pkg-path` directly. The
catalog moves forward — verify any version named in this guidance against
today's `flox show` before relying on it.

Two reasons the range sits last. It is less precise than it looks — `"^22.0"`
and `nodejs_22` express the same intent, but only the second one survives a
reader asking "which Node is this?". And a range is not verifiable: it names a
constraint rather than a catalog version, so tooling that checks a manifest
against the catalog (`floxify`'s `verify.py`, for one) cannot tell which
version applies and records the entry as unchecked rather than confirmed. A
versioned `pkg-path` or a literal pin gets checked; a range silently drops out
of verification.

**systems**
- Constrains package to specific platforms
- Options: `"x86_64-linux"`, `"x86_64-darwin"`, `"aarch64-linux"`, `"aarch64-darwin"`
- Defaults to manifest's `options.systems` if omitted
- Rely on the default enabled set (Flox >= 1.15: `aarch64-darwin`,
  `aarch64-linux`, `x86_64-linux`). Declare `systems` to LIMIT an
  environment to a known-working subset (e.g. CUDA: Linux only)
- `x86_64-darwin` is deprecated upstream and off by default — explicit
  opt-in only: naming it in a `<id>.systems` without also declaring it
  in `[options] systems` fails activation ("specifies disabled or
  unknown system", verified live on 1.15.0)

**priority**
- Resolves file conflicts between packages
- Default: 5
- Lower number = higher priority wins conflicts
- **Critical for CUDA packages** (see `references/cuda.md`)

### Practical Examples

```toml
# Platform-specific Python (constrain per package with <id>.systems)
[install]
python.pkg-path = "python311Full"
python.systems = ["x86_64-linux", "aarch64-linux"]  # Linux only
uv.pkg-path = "uv"
uv.systems = ["x86_64-linux", "aarch64-linux"]

# Versioned pkg-path with custom priority — every key is <id>.-prefixed under [install]
nodejs.pkg-path = "nodejs_22"
nodejs.priority = 1  # Takes precedence in conflicts

# Separate package groups to avoid version conflicts
gcc.pkg-path = "gcc12"
gcc.pkg-group = "stable"
```

## Language-Specific Patterns

### Python Virtual Environments

**venv creation pattern**: Always check existence before activation:
```bash
if [ ! -d "$venv" ]; then
  uv venv "$venv" --python python3
fi
# Guard activation - venv creation might not be complete
if [ -f "$venv/bin/activate" ]; then
  source "$venv/bin/activate"
fi
```

**Key patterns**:
- **venv location**: Always use `$FLOX_ENV_CACHE/venv` - survives environment rebuilds
- **uv with venv**: Use `uv pip install --python "$venv/bin/python"` NOT `"$venv/bin/python" -m uv`
- **Cache dirs**: Set `UV_CACHE_DIR` and `PIP_CACHE_DIR` to `$FLOX_ENV_CACHE` subdirs
- **Dependency installation flag**: Touch `$FLOX_ENV_CACHE/.deps_installed` to prevent reinstalls

### C/C++ Development

- **Package Names**: `gbenchmark` not `benchmark`, `catch2_3` for Catch2, `gcc13`/`clang_18` for specific versions
- **System Constraints**: Linux-only tools need explicit systems: `valgrind.systems = ["x86_64-linux", "aarch64-linux"]`
- **Essential Groups**: Separate `compilers`, `build`, `debug`, `testing`, `libraries` groups prevent conflicts
- **libstdc++ Access**: ALWAYS include `gcc-unwrapped` for C++ stdlib headers/libs (gcc alone doesn't expose them):
```toml
# eval: skip fragment - package descriptors, go under [install]
gcc-unwrapped.pkg-path = "gcc-unwrapped"
gcc-unwrapped.priority = 5
gcc-unwrapped.pkg-group = "libraries"
```

### Node.js Development

- **Package managers**: Install `nodejs` (includes npm); add `yarn` or `pnpm` separately if needed
- **Version pinning**: Use the versioned pkg-path for an LTS line — `nodejs.pkg-path = "nodejs_22"`, no `version` field. Add `version = "22.11.0"` alongside it when the repo pins an exact patch (`.nvmrc`, `.node-version`). Check which majors the catalog carries with `flox search nodejs_`
- **Global tools pattern**: Use `npx` for one-off tools, install commonly-used globals in manifest

### Platform-Specific Patterns

```toml
# eval: skip fragment - package descriptors, go under [install]
# Darwin-specific frameworks
IOKit.pkg-path = "darwin.apple_sdk.frameworks.IOKit"
IOKit.systems = ["aarch64-darwin"]

# Platform-preferred compilers
gcc.pkg-path = "gcc"
gcc.systems = ["x86_64-linux", "aarch64-linux"]
clang.pkg-path = "clang"
clang.systems = ["aarch64-darwin"]

# Darwin GNU compatibility layer
coreutils.pkg-path = "coreutils"
coreutils.systems = ["aarch64-darwin"]
```

Intel macOS (`x86_64-darwin`) is deprecated upstream and outside the
default enabled set — only for an explicit need, add it to the relevant
scopes AND declare it in `[options] systems`, and expect gaps.

## Best Practices

- Check manifest before installing new packages
- Use `return` not `exit` in hooks
- Define env vars with `${VAR:-default}`
- Use descriptive, prefixed function names in composed envs
- Cache downloads in `$FLOX_ENV_CACHE`
- Test activation with `flox activate -- <command>` before adding to services
- Use `--quiet` flag with uv/pip in hooks to reduce noise

## Editing Manifests Non-Interactively

```bash
flox list -c > /tmp/manifest.toml
# Edit with sed/awk
flox edit -f /tmp/manifest.toml
```

## Common Pitfalls

### Hooks Run Every Activation
Hooks run EVERY activation (keep them fast/idempotent)

### Hook vs Profile Functions
Hook functions are not available to users in the interactive shell; use `[profile]` for user-invokable commands/aliases

### Profile Code in Layered Environments
Profile code runs for each layered/composed environment; keep auto-run display logic in `[hook]` to avoid repetition

### Manifest Syntax Errors
Manifest syntax errors prevent ALL flox commands from working

### Package Search Is Case-Insensitive
Package search matches case-insensitively; use `flox search --all` for broader results

## Troubleshooting Tips

### Package Conflicts
If packages conflict, use different `pkg-group` values or adjust `priority`

### Tricky Dependencies
- If we need `libstdc++`, we get this from the `gcc-unwrapped` package, not from `gcc`
- If user is working with python and requests `uv`, they typically do not mean `uvicorn`; clarify which package user wants

### Hook Issues
- Use `return` not `exit` in hooks
- Define env vars with `${VAR:-default}`
- Guard FLOX_ENV_CACHE usage: `${FLOX_ENV_CACHE:-}` with fallback

