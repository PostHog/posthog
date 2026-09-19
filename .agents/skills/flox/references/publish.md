# Flox Package Publishing Guide

## Core Commands

```bash
flox publish                    # Publish the sole build (only when one is defined)
flox publish my_package         # Publish single package
flox publish -o myorg package   # Publish to organization
flox publish -o myuser package  # Publish to personal namespace
flox auth login                 # Authenticate before publishing
```

## Publishing Workflow: Development to Runtime

Publishing packages enables a clear separation between **development** and **runtime/consumption**:

### The Complete Workflow

**Phase 1: Development Environment**
```toml
# .flox/env/manifest.toml (in git with source code)
[install]
gcc.pkg-path = "gcc13"
make.pkg-path = "make"
python.pkg-path = "python311Full"

[build.myapp]
command = '''
  python setup.py build
  mkdir -p $out/bin
  cp build/myapp $out/bin/
'''
version = "1.0.0"
```

Developers work in this environment, commit `.flox/` to git alongside source code.

**Phase 2: Build and Publish**
```bash
# Build the package
flox build myapp

# Publish to catalog
flox publish -o myorg myapp
```

The published package contains BINARIES/ARTIFACTS (what's in `$out/`) — not source code, unless the build copies it into `$out/`.

**Phase 3: Runtime Environment**
```toml
# Separate environment (can be pushed to FloxHub)
[install]
myapp.pkg-path = "myorg/myapp"  # The published package
```

Consumers create runtime environments and install the published package. No build tools needed, no source code exposed.

**Key insight**: You don't install the published package back into the development environment - that would be circular. Published packages are installed into OTHER environments (different projects, production, etc.).

## Publishing to Flox Catalog

### Prerequisites
Before publishing:
- Package defined in `[build]` section or `.flox/pkgs/`
- Environment in Git repo with configured remote
- Clean working tree (no uncommitted changes)
- Current commit pushed to remote
- All build files tracked by Git
- At least one package installed in `[install]`
- **A full clone, not a shallow one** — see below

**Never publish from a shallow clone.** `flox publish` records the repository's
commit count as build provenance, taken from `git rev-list --count`. In a
`--depth 1` clone that command returns `1` and exits 0, so a repository with
five hundred commits publishes as though it had one.

Nothing catches this. There is no shallow-clone check in the publish path, the
command succeeds, and the wrong number is what lands in the catalog. That makes
it worse than an error, not better: a failed publish is visible, and this one
looks exactly like a good publish until someone reads the provenance back.

Check before you publish, and unshallow if needed:

```bash
git rev-parse --is-shallow-repository   # must print false
git fetch --unshallow                   # if it printed true
```

CI is where this bites most, because shallow is the default there rather than
something you asked for. See the GitHub Actions and GitLab examples below.

### Authentication

Run authentication before first publish:
```bash
flox auth login
```

### Publishing Commands

```bash
# Publish single package
flox publish my_package

# Publish the single defined build (errors if there are several — name one)
flox publish

# Publish to organization
flox publish -o myorg my_package

# Publish to personal namespace (for testing)
flox publish -o mypersonalhandle my_package
```

### Catalog Types

**Personal catalogs**: Only visible to you (good for testing)
- Published to your personal namespace
- Example: User "alice" publishes "hello" → available as `alice/hello`
- Useful for testing before publishing to organization

**Organization catalogs**: Shared with team members (paid feature)
- Published to organization namespace
- Example: Org "acme" publishes "tool" → available as `acme/tool`
- All organization members can install

### Build Validation

Flox clones your repo to a temp location and performs a clean build to ensure reproducibility. Only packages that build successfully in this clean environment can be published.

This validation ensures:
- All dependencies are declared
- Build is reproducible
- No reliance on local machine state
- Git repository is clean and up-to-date

### After Publishing

- Package available in `flox search`, `flox show`, `flox install`
- Metadata sent to Flox servers
- Package binaries uploaded to Catalog Store
- Install with: `flox install <catalog>/<package>`

Users can then:
```bash
# Search for your package
flox search my_package

# See package details
flox show myorg/my_package

# Install the package
flox install myorg/my_package
```

### What Gets Published

**Published packages contain:**
- Binaries and compiled artifacts (everything in `$out/`)
- Runtime dependencies specified in `runtime-packages`
- Package metadata (version, description)

**Published packages do NOT contain:**
- Source code (unless explicitly copied to `$out/`)
- Build tools or build-time dependencies
- Development environment configuration
- The `.flox/` directory itself

This separation allows you to share built artifacts without exposing source code.

## Real-world Publishing Workflows

### Application Development Workflow

**Developer workflow:**
1. Create development environment with build tools:
   ```bash
   mkdir myapp && cd myapp
   flox init
   flox install gcc make python311Full
   ```

2. Add source code and build definition to `.flox/env/manifest.toml`:
   ```toml
   [build.myapp]
   command = '''make && cp myapp $out/bin/'''
   version = "1.0.0"
   ```

3. Commit to git (environment definition + source code):
   ```bash
   git add .flox/ src/
   git commit -m "Add development environment and source"
   git push origin main
   ```

4. Build and publish package (binaries/artifacts):
   ```bash
   flox build myapp
   flox publish -o myorg myapp
   ```

**Other developers:**
- Clone repo: `git clone <repo> && cd myapp && flox activate`
- Get the same development environment with build tools

**Consumers:**
- Create new runtime environment: `flox init && flox install myorg/myapp`
- OR install into existing environment: `flox install myorg/myapp`
- Get the BUILT package (binaries), not source code
- Can push runtime environment to FloxHub without exposing source

### Fork-based Development Pattern

1. Fork upstream repo (e.g., `user/project` from `upstream/project`)
2. Add `.flox/` to fork with build definitions
3. Commit and push: `git push origin main`
4. Publish package: `flox publish -o username package-name`
5. Others can install: `flox install username/package-name`

## Versioning Strategies

### Semantic Versioning

```toml
# eval: skip fragment - metadata fields only, merge into a [build.<name>] that has a command
[build.mytool]
version = "1.2.3"  # Major.Minor.Patch
description = "My awesome tool"
```

### Git-based Versioning

```toml
# eval: skip fragment - metadata fields only, merge into a [build.<name>] that has a command
[build.mytool]
version.command = "git describe --tags"
description = "My awesome tool"
```

### File-based Versioning

```toml
# eval: skip fragment - metadata fields only, merge into a [build.<name>] that has a command
[build.mytool]
version.file = "VERSION.txt"
description = "My awesome tool"
```

### Dynamic Versioning from Source

```toml
# eval: skip fragment - metadata fields only, merge into a [build.<name>] that has a command
[build.rustapp]
version.command = "cargo metadata --no-deps --format-version 1 | jq -r '.packages[0].version'"
```

## Publishing Multiple Variants

You can publish multiple variants of the same project:

```toml
[build.myapp]
command = '''
  cargo build --release
  mkdir -p $out/bin
  cp target/release/myapp $out/bin/
'''
version = "1.0.0"
description = "Production build"
sandbox = "pure"

[build.myapp-debug]
command = '''
  cargo build
  mkdir -p $out/bin
  cp target/debug/myapp $out/bin/myapp-debug
'''
version = "1.0.0"
description = "Debug build with symbols"
sandbox = "off"
```

Both can be published and users can choose which to install.

## Testing Before Publishing

### Local Testing

1. Build the package:
```bash
flox build myapp
```

2. Test the built artifact:
```bash
./result-myapp/bin/myapp --version
```

3. Install locally to test:
```bash
flox install ./result-myapp
```

### Personal Catalog Testing

Publish to your personal namespace first:
```bash
flox publish -o myusername myapp
```

Then test installation:
```bash
flox install myusername/myapp
```

Once validated, republish to organization:
```bash
flox publish -o myorg myapp
```

## Common Gotchas

### Branch names
Many repos use `master` not `main` - check with `git branch`

### Auth required
Run `flox auth login` before first publish

### Clean git state
Commit and push ALL changes before `flox publish`:
```bash
git status  # Check for uncommitted changes
git add .flox/
git commit -m "Add flox build configuration"
git push origin master
```

### runtime-packages
List only what package needs at runtime, not build deps:
```toml
[install]
gcc.pkg-path = "gcc"
make.pkg-path = "make"

[build.myapp]
command = '''make && cp myapp $out/bin/'''
runtime-packages = []  # No runtime deps needed
```

### Git-tracked files only
All files referenced in build must be tracked:
```bash
git add .flox/pkgs/*
git add src/
git commit -m "Add build files"
```

## Publishing Nix Expression Builds

For Nix expression builds in `.flox/pkgs/`:

1. Create the Nix expression:
```bash
mkdir -p .flox/pkgs
cat > .flox/pkgs/hello.nix << 'EOF'
{ hello }:
hello.overrideAttrs (oldAttrs: {
  patches = (oldAttrs.patches or []) ++ [ ./my.patch ];
})
EOF
```

2. Track with Git:
```bash
git add .flox/pkgs/*
git commit -m "Add hello package"
git push
```

3. Publish:
```bash
flox publish hello
```

## Publishing Configuration and Assets

You can publish non-code artifacts:

### Configuration templates

```toml
[build.nginx-config]
command = '''
  mkdir -p $out/etc
  cp nginx.conf $out/etc/
  cp -r conf.d $out/etc/
'''
version = "1.0.0"
description = "Organization Nginx configuration"
```

### Protocol buffers

```toml
[build.api-proto]
command = '''
  mkdir -p $out/share/proto
  cp proto/**/*.proto $out/share/proto/
'''
version = "2.1.0"
description = "API protocol definitions"
```

Teams install and reference via `$FLOX_ENV/etc/` or `$FLOX_ENV/share/`.

## Continuous Integration Publishing

A publish job presumes the build already has its own CI verification — a
`flox build <target>` job running on every PR, per `references/builds.md`
§ The Build Job Travels With the Target. Wire that first; a publish-on-main
job is a poor place to discover a stale `vendorHash`.

### GitHub Actions Example

```yaml
name: Publish to Flox

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          fetch-depth: 0

      - name: Install Flox
        uses: flox/install-flox-action@1128abd73431089ab9d871c893b4e72a729354e1 # v2.6.0

      - name: Publish
        env:
          FLOX_FLOXHUB_TOKEN: ${{ secrets.FLOX_FLOXHUB_TOKEN }}
        run: flox publish -o myorg mypackage
```

**Publish from a branch, not a tag.** `actions/checkout` checks a tag out in
detached HEAD, and `flox publish` refuses to publish from one:

```
Repository is in detached HEAD state and has no upstream remote configured.
Check out a branch before publishing: `git checkout -b <branch-name>`
```

There is nothing a tag-triggered job can do about that, so trigger on the push
to your release branch instead.

`fetch-depth: 0` is not optional here. `actions/checkout` clones at depth 1 by
default, and a depth-1 clone publishes successfully with a commit count of `1`
regardless of the repository's real history, silently, as described under
[Prerequisites](#prerequisites). Every publish from that workflow carries the
same wrong provenance, and the job stays green while it happens.

`install-flox-action` installs the CLI; it does not activate an environment.
This job does not need one: `flox publish` acts on the environment directory,
so it needs `flox` on `PATH`, not the environment's contents. Reach for
`flox/activate-action` or a `flox activate` shell only when a step runs
something the environment *provides* — see `references/ci.md`.

### GitLab CI Example

```yaml
publish:
  stage: deploy
  # Flox comes from the job image (ghcr.io/flox/flox), not a step
  variables:
    GIT_DEPTH: 0        # GitLab shallow-clones by default; see Prerequisites
  only:
    - main
  script:
    - flox publish -o myorg mypackage
```

Both constraints from the GitHub example carry over. A GitLab tag pipeline also
checks out a detached HEAD, which `flox publish` refuses. And GitLab clones
shallow by default, so `GIT_DEPTH: 0` is the counterpart of `fetch-depth: 0`:
without it every publish from this job records the same wrong commit count,
without failing.

Set `FLOX_FLOXHUB_TOKEN` as a masked CI/CD variable; GitLab exports it into the
job, so `flox publish` picks it up with no separate login step. Run the job in
`ghcr.io/flox/flox`, which already has the CLI; where the image is fixed,
`curl -fsSL https://get.flox.dev | sh` as the first script step is the
supported fallback. As above, publishing needs the CLI on
`PATH`, not an activated environment.

## Package Metadata Best Practices

### Good Descriptions

```toml
# eval: skip fragment - metadata fields only, merge into a [build.<name>] that has a command
[build.cli]
description = "High-performance log shipper with filtering"  # Good: specific, descriptive

# Avoid:
# description = "My tool"  # Too vague
# description = "CLI"      # Not descriptive enough
```

### Proper Versioning

- Use semantic versioning: MAJOR.MINOR.PATCH
- Increment MAJOR for breaking changes
- Increment MINOR for new features
- Increment PATCH for bug fixes

### Runtime Dependencies

Only include what's actually needed at runtime:

```toml
# eval: skip fragment - metadata fields only, merge into a [build.<name>] that has a command
[install]
# Build-time only
gcc.pkg-path = "gcc"
make.pkg-path = "make"
# Runtime dependency
libssl.pkg-path = "openssl"

[build.myapp]
runtime-packages = ["libssl"]  # Only runtime deps
```

