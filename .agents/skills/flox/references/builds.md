# Flox Build System Guide

## Build System Overview

Flox supports two build modes, each with its own strengths:

**Manifest builds** enable you to define your build steps in your manifest and reuse your existing build scripts and toolchains. Flox manifests are declarative artifacts, expressed in TOML.

Manifest builds:
- Make it easy to get started, requiring few if any changes to your existing workflows
- Can run inside a sandbox (using `sandbox = "pure"`) for reproducible builds
- Are best for getting going fast with existing projects

**Nix expression builds** guarantee build-time reproducibility because they're both isolated and purely functional. Their learning curve is steeper because they require proficiency with the Nix language.

Nix expression builds:
- Are isolated by default. The Nix sandbox seals the build off from the host system, so no state leak ins
- Are functional. A Nix build is defined as a pure function of its declared inputs

You can mix both approaches in the same project, but package names must be unique.

## Core Commands

```bash
flox build                      # Build all targets
flox build app docs             # Build specific targets
flox build -d /path/to/project  # Build in another directory
flox build -v                   # Verbose output
flox build .#hello              # Build specific Nix expression
```

## Development vs Runtime: The Two-Environment Pattern

A common workflow involves **two separate environments**:

### Development Environment (Build-Time)
Contains source code, build tools, and build definitions:
```toml
# project-dev/.flox/env/manifest.toml (in git with source code)
[install]
gcc.pkg-path = "gcc13"
make.pkg-path = "make"
python.pkg-path = "python311Full"
uv.pkg-path = "uv"

[build.myapp]
command = '''
  make build
  mkdir -p $out/bin
  cp build/myapp $out/bin/
'''
version = "1.0.0"
```

**Workflow:**
```bash
cd project-dev
flox activate
flox build myapp
flox publish -o myorg myapp
```

### Runtime Environment (Consume-Time)
Contains only the published package and runtime dependencies:
```toml
# project-runtime/.flox/env/manifest.toml (can push to FloxHub)
[install]
myapp.pkg-path = "myorg/myapp"  # The published package
```

**Workflow:**
```bash
cd project-runtime
flox init
flox install myorg/myapp
flox push  # Share runtime environment without source code
```

**Why separate environments?**
- Development environment: Heavy (build tools, source code, dev dependencies)
- Runtime environment: Lightweight (only published package and runtime needs)
- Security: Runtime environments don't expose source code
- Clarity: Clear separation between building and consuming
- Rollback: Can rollback the live generation of a runtime environment without affecting the development environment

**Note**: You can also install published packages into existing environments (other projects, production environments, etc.), not just dedicated runtime environments.

## Manifest Builds

Flox treats a **manifest build** as a short, deterministic Bash script that runs inside an activated environment and copies its deliverables into `$out`. Anything copied there becomes a first-class, versioned package that can later be published and installed like any other catalog artifact.

### Critical insights from real-world packaging:
- **Build hooks don't run**: `[hook]` scripts DO NOT execute during `flox build` - only during interactive `flox activate`
- **Guard env vars**: Always use `${FLOX_ENV_CACHE:-}` with default fallback in hooks to avoid build failures
- **Wrapper scripts pattern**: Create launcher scripts in `$out/bin/` that set up runtime environment:
  ```bash
  cat > "$out/bin/myapp" << 'EOF'
  #!/usr/bin/env bash
  APP_ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"
  export PYTHONPATH="$APP_ROOT/share/myapp:$PYTHONPATH"
  exec python3 "$APP_ROOT/share/myapp/main.py" "$@"
  EOF
  chmod +x "$out/bin/myapp"
  ```
- **User config pattern**: Default to `~/.myapp/` for user configs, not `$FLOX_ENV_CACHE` (packages are immutable)
- **Model/data directories**: Create user directories at runtime, not build time:
  ```bash
  mkdir -p "${MYAPP_DIR:-$HOME/.myapp}/models"
  ```
- **Python package strategy**: Don't bundle Python deps - include `requirements.txt` and setup script:
  ```bash
  # In build, create setup script:
  cat > "$out/bin/myapp-setup" << 'EOF'
  venv="${VENV:-$HOME/.myapp/venv}"
  uv venv "$venv" --python python3
  uv pip install --python "$venv/bin/python" -r "$APP_ROOT/share/myapp/requirements.txt"
  EOF
  ```
- **Dual-environment workflow**: Use one environment for building (`project-dev/`), another for consuming (`project-runtime/`). See "Development vs Runtime: The Two-Environment Pattern" section above for details.

### Build Definition Syntax

```toml
# eval: skip fragment - syntax template with <placeholders>
[build.<name>]
command      = '''  # required – Bash, multiline string
  <your build steps>                 # e.g. cargo build, npm run build
  mkdir -p $out/bin
  cp path/to/artifact $out/bin/<name>
'''
version      = "1.2.3"               # optional
description  = "one-line summary"    # optional
sandbox      = "off" | "warn" | "enforce" | "pure"   # default: off
                                     # "warn"/"enforce" need schema-version "1.13.0"+
sandbox-allow = [ "~/.npm/**" ]      # optional; schema-version "1.13.0"+
runtime-packages = [ "id1", "id2" ]  # optional
```

**One table per package.** Multiple `[build.*]` tables let you publish, for example, a stripped release binary and a debug build from the same sources.

**Bash only.** The script executes under `set -euo pipefail`. If you need zsh or fish features, invoke them explicitly inside the script.

**Environment parity.** Before your script runs, Flox performs the equivalent of `flox activate` — so every tool listed in `[install]` is on PATH.

**Package groups and builds.** Only packages in the `toplevel` group (default) are available during builds. Packages with explicit `pkg-group` settings won't be accessible in build commands unless also installed to `toplevel`.

**Referencing other builds.** `${other}` expands to the `$out` of `[build.other]` and forces that build to run first, enabling multi-stage flows (e.g. vendoring → compilation).

## Purity and Sandbox Control

| sandbox value | Filesystem scope | Network | Typical use-case |
|---------------|------------------|---------|------------------|
| `"off"` (default) | Project working tree; complete host FS | allowed | Fast, iterative dev builds |
| `"warn"` | Same as `"off"`, but each read from outside the package closure is reported | allowed | Finding undeclared dependencies without breaking the build |
| `"enforce"` | Reads from outside the package closure are denied | allowed | Failing the build on undeclared dependencies, without full purity |
| `"pure"` | Git-tracked files only, copied to tmp | Linux: blocked<br>macOS: allowed | Reproducible, host-agnostic packages |

**`"warn"` and `"enforce"` require `schema-version = "1.13.0"` or newer.** Under
`version = 1` they fail to parse with ``unknown variant `warn`, expected `off`
or `pure` `` — the message points at the value, but the fix is the manifest's
version line (see `references/schema-versions.md`).

`sandbox-allow` (same 1.13.0 requirement) exempts specific paths from the
`"warn"`/`"enforce"` check. A leading `~/` expands to `$HOME`, and `*`/`**`
match across path separators. The key has no effect under `"off"` or `"pure"`.

⚠ **A pattern containing a space will not match**, even though it parses
cleanly — the list is space-joined into a single value handed to the sandbox,
so a space splits one pattern into two. Give a directory with a space in its
name a glob that avoids the space (`"~/*/**"`) or move the path.

```toml
schema-version = "1.13.0"

[build.app]
command = '''
  npm ci
  mkdir -p $out/bin
  cp -r dist $out/
'''
sandbox = "warn"
sandbox-allow = [ "~/.npm/**" ]
```

Pure mode highlights undeclared inputs early and is mandatory for builds intended for CI/CD publication. When a pure build needs pre-fetched artifacts (e.g. language modules) use a two-stage pattern:

```toml
[build.deps]
command  = '''go mod vendor -o $out/etc/vendor'''
sandbox  = "off"

[build.app]
command  = '''
  cp -r ${deps}/etc/vendor ./vendor
  go build ./...
  mkdir -p $out/bin
  cp app $out/bin/
'''
sandbox  = "pure"
```

## $out Layout and Filesystem Hierarchy

Only files placed under `$out` survive. Follow FHS conventions:

| Path | Purpose |
|------|---------|
| `$out/bin` / `$out/sbin` | CLI and daemon binaries (must be `chmod +x`) |
| `$out/lib`, `$out/libexec` | Shared libraries, helper programs |
| `$out/share/man` | Man pages (gzip them) |
| `$out/etc` | Configuration shipped with the package |

Scripts or binaries stored elsewhere will not end up on callers' paths.

## Running Manifest Builds

```bash
# Build every target in the manifest
flox build

# Build a subset
flox build app docs

# Build a manifest in another directory
flox build -d /path/to/project
```

Results appear as immutable symlinks: `./result-<name>` → `/nix/store/...-<name>-<version>`.

To execute a freshly built binary: `./result-app/bin/app`.

## Multi-Stage Examples

### Rust release binary plus source tar

```toml
[build.bin]
command = '''
  cargo build --release
  mkdir -p $out/bin
  cp target/release/myproject $out/bin/
'''
version = "0.9.0"

[build.src]
command = '''
  git archive --format=tar HEAD | gzip > $out/myproject-${bin.version}.tar.gz
'''
sandbox = "pure"
```

`${bin.version}` resolves because both builds share the same manifest.

### Go with vendored dependencies

```toml
[build.vendor]
command = '''
  go mod vendor
  mkdir -p $out/vendor
  cp -r vendor/* $out/vendor/
'''
sandbox = "off"

[build.app]
command = '''
  cp -r ${vendor}/vendor ./
  go build -mod=vendor -o $out/bin/myapp
'''
sandbox = "pure"
```

## Trimming Runtime Dependencies

By default, every package in the `toplevel` install-group becomes a runtime dependency of your build's closure—even if it was only needed at compile time.

Declare a minimal list instead:

```toml
[install]
clang.pkg-path = "clang"
pytest.pkg-path = "pytest"

[build.cli]
command = '''
  make
  mv build/cli $out/bin/
'''
runtime-packages = [ "clang" ]  # exclude pytest from runtime closure
```

Smaller closures copy faster and occupy less disk when installed on users' systems.

**Common mistake:** there is no `packages` key in a `[build.<name>]` section. To
exclude build-only tools from the runtime closure the key is `runtime-packages`
(a KEEP-list of install ids) — not `packages`, and not the Nix `buildInputs`
habit. If the toolchain is leaking into your package, reach for `runtime-packages`:

```toml
[build.cli]
command = '''
  make
  mv build/cli $out/bin/
'''
# WRONG: packages = [ "clang" ]   <- no such key in a build section
runtime-packages = [ "clang" ]    # RIGHT: keep only clang at runtime
```

## Version and Description Metadata

Flox surfaces these fields in `flox search`, `flox show`, and during publication.

```toml
# eval: skip fragment - metadata fields only, merge into a [build.<name>] that has a command
[build.mytool]
version.command = "git describe --tags"
description = "High-performance log shipper"
```

Alternative forms:

```toml
# eval: skip fragment - alternative forms of one field
version = "1.4.2"            # static string
version.file = "VERSION.txt" # read at build time
```

## Cross-Platform Considerations for Manifest Builds

`flox build` targets the host's systems triple. To ship binaries for additional platforms you must trigger the build on machines (or CI runners) of those architectures:

```
linux-x86_64 → build → publish
darwin-aarch64 → build → publish
```

The manifest can remain identical across hosts.

## Beyond Code — Packaging Assets

Any artifact that can be copied into `$out` can be versioned and installed:

### Nginx baseline config

```toml
[build.nginx_cfg]
command = '''mkdir -p $out/etc && cp nginx.conf $out/etc/'''
```

### Organization-wide .proto schema bundle

```toml
[build.proto]
command = '''
  mkdir -p $out/share/proto
  cp proto/**/*.proto $out/share/proto/
'''
```

Teams install these packages and reference them via `$FLOX_ENV/etc/nginx.conf` or `$FLOX_ENV/share/proto`.

## Nix Expression Builds

You can write a Nix expression instead of (or in addition to) defining a manifest build.

This is also the answer to **"the catalog's version is too old"** or **"the package
isn't in Flox yet."** The Flox Catalog tracks nixpkgs with a short lag, so rather
than waiting you can override the existing recipe to a newer release (see "Update
Version" below), or package a missing tool from scratch — then `flox publish` it so
the result installs in any environment. Worked end-to-end walkthrough:
[Using a newer version of a package](https://flox.dev/docs/tutorials/overriding-packages/).

Put `*.nix` build files in `.flox/pkgs/` for Nix expression builds. Git add all files before building.

### File Naming
- `hello.nix` → package named `hello`
- `hello/default.nix` → package named `hello`

### Common Patterns

**Shell Script**
```nix
{writeShellApplication, curl}:
writeShellApplication {
  name = "my-ip";
  runtimeInputs = [ curl ];
  text = ''curl icanhazip.com'';
}
```

**Your Project**
```nix
{ rustPlatform, lib }:
rustPlatform.buildRustPackage {
  pname = "my-app";
  version = "0.1.0";
  src = ../../.;
  cargoLock.lockFile = "${src}/Cargo.lock";
}
```

**Update Version** — get a newer release than the catalog carries. Override the
existing recipe's `version`/`src`; leave `hash = ""` first so `flox build` prints
the correct hash to paste back. Then `flox publish <name>` (requires a git remote
with all `.flox/pkgs/` files committed and pushed) to make it installable anywhere.
```nix
{ hello, fetchurl }:
hello.overrideAttrs (finalAttrs: _: {
  version = "2.12.2";
  src = fetchurl {
    url = "mirror://gnu/hello/hello-${finalAttrs.version}.tar.gz";
    hash = "sha256-WpqZbcKSzCTc9BHO6H6S9qrluNE72caBm0x6nc4IGKs=";
  };
})
```

**Apply Patches**
```nix
{ hello }:
hello.overrideAttrs (oldAttrs: {
  patches = (oldAttrs.patches or []) ++ [ ./my.patch ];
})
```

### Hash Generation
1. Use `hash = "";`
2. Run `flox build`
3. Copy hash from error message

### Commands
- `flox build` - build all
- `flox build .#hello` - build specific
- `git add .flox/pkgs/*` - track files

## Language-Specific Build Examples

### Python Application

```toml
[build.myapp]
command = '''
  mkdir -p $out/bin $out/share/myapp

  # Copy application code
  cp -r src/* $out/share/myapp/
  cp requirements.txt $out/share/myapp/

  # Create wrapper script
  cat > $out/bin/myapp << 'EOF'
#!/usr/bin/env bash
APP_ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"
export PYTHONPATH="$APP_ROOT/share/myapp:$PYTHONPATH"
exec python3 "$APP_ROOT/share/myapp/main.py" "$@"
EOF
  chmod +x $out/bin/myapp
'''
version = "1.0.0"
```

### Node.js Application

```toml
[build.webapp]
command = '''
  npm ci
  npm run build

  mkdir -p $out/share/webapp
  cp -r dist/* $out/share/webapp/
  cp package.json package-lock.json $out/share/webapp/

  cd $out/share/webapp && npm ci --production
'''
version = "1.0.0"
```

### Rust Binary

```toml
[build.cli]
command = '''
  cargo build --release
  mkdir -p $out/bin
  cp target/release/mycli $out/bin/
'''
version.command = "cargo metadata --no-deps --format-version 1 | jq -r '.packages[0].version'"
```

## The Build Job Travels With the Target

A build target ships with a CI job that runs it: the commit that adds a
`[build.*]` section or a `.flox/pkgs/*.nix` also adds a job running
`flox build <target>` from a clean checkout — in whatever CI system the repo
already uses (detect it from the config files present; `references/ci.md`
§ Other CI systems lists the official integrations per system). When you
create a target for someone else's repo, offering that job is part of the
deliverable — in the same change, not as advice for later, and as an offer
the maintainer accepts, never a file written silently. If the repo's CI
system is one you can't cleanly conform to, or the repo has no CI, recommend
the job and ask the user where it should live rather than imposing a vendor.

**This job is verification, not the release pipeline.** It exists to keep a
pull request from landing the silent break; how artifacts are produced and
distributed after merge is a separate concern this job neither performs nor
forecloses. Flox's direction for that is the Factory — automatic builds once
a package is registered — so mention it as where build/publish automation is
headed, but don't present registration as a self-serve step available today,
and don't tell users their CI is forbidden from building or caching. The
distinction to keep sharp with users: the dev environment (`flox activate`,
what floxify sets up, high confidence) and a working built artifact
(`flox build`, a step deeper with more edge cases) are different promises —
verify each with its own job, and never let a build failure be someone's
first Flox experience.

The reason is that the dev loop keeps passing while packaging rots. Two failure
classes surface ONLY on a from-scratch build:

- **Fetched-deps hash drift.** A Nix expression build pins its dependency
  closure with a hash (`vendorHash`, `cargoHash`, `npmDepsHash`). Every
  dependency bump invalidates it, and nothing in the dev loop notices —
  `go build` and `go test` in the activated environment never consult the
  hash. The break lands on `main` silently and is discovered by the next
  person who follows the README's `flox build` instructions.
- **Sandbox-only gaps.** A tool present in the dev environment (say, `git` on
  `PATH`, or added at runtime by a `wrapProgram`) is absent from the build's
  declared inputs, so a `checkPhase` that shells out to it fails only inside
  the sandbox. Tests pass locally forever; the build is broken the whole time.

The job itself is small — GitHub Actions shown as the worked example, same
shape in any system (get `flox` onto the runner, run `flox build <target>`).
This is a complete standalone workflow; when the repo already has a Flox
workflow (e.g. floxify's `flox.yml`), add just the job block to it instead:

```yaml
name: Flox build

on:
  push:
    branches: [<default branch>]
  pull_request:

jobs:
  flox-build:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
    runs-on: ${{ matrix.os }}
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@<full SHA> # <tag>
      - uses: flox/install-flox-action@<full SHA> # <tag>
      - run: flox build <target>
```

- No activation step: `flox build` acts on the environment directory, so it
  needs `flox` on `PATH`, not the environment's contents — the same
  install-is-not-activation split `references/ci.md` opens with. Pin the
  action SHAs per that file's § Pinning.
- Matrix over the platforms the package already declares — `meta.platforms`
  for a Nix expression, the manifest's `options.systems` for a manifest
  build. The job verifies what the package claims to support; it doesn't
  expand the claim.
- A green job only *blocks* regressions if the repo makes it a required
  status check (branch protection). Without that it makes breakage visible,
  not unmergeable — worth one line in your report when you wire the job for
  someone else, since flipping that setting is theirs to do.

Publishing from CI is the separate, later step — `references/publish.md`
§ Continuous Integration Publishing.

## Debugging Build Issues

### Common Problems

**Build hooks don't run**: `[hook]` scripts DO NOT execute during `flox build`

**Package groups**: Only `toplevel` group packages available during builds

**Network access**: Pure builds can't access network on Linux

### Debugging Steps

1. Check build output: `flox build -v`
2. Inspect result: `ls -la result-<name>/`
3. Test binary: `./result-<name>/bin/<name>`
4. Check dependencies: `nix-store -q --references result-<name>`

