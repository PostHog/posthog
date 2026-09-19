# Flox Sharing, Composition & Layering

## Environment Layering

### What is Layering?

**Layering** is runtime stacking of environments where activate order matters. Each layer runs in its own subshell, preserving isolation while allowing tool composition.

### Core Layering Commands

```bash
# Layer debugging tools on base environment
flox activate -r team/base -- flox activate -r team/debug

# Layer multiple environments
flox activate -r team/db -- flox activate -r team/cache -- flox activate

# Layer local on remote
flox activate -r prod/app -- flox activate
```

### When to Use Layering

- **Ad hoc tool addition**: Add debugging/profiling tools temporarily
- **Development vs production**: Layer dev tools on production environment
- **Flexible composition**: Mix and match environments at runtime
- **Temporary utilities**: Add one-time tools without modifying environment

### Layering Use Cases

**Development tools on production environment:**
```bash
flox activate -r prod/app -- flox activate -r dev/tools
```

**Debugging tools on CUDA environment:**
```bash
flox activate -r team/cuda-base -- flox activate -r team/cuda-debug
```

**Temporary utilities:**
```bash
flox activate -r project/main -- flox activate -r utils/network
```

### Creating Layer-Optimized Environments

**Design for runtime stacking with potential conflicts:**

```toml
[vars]
# Prefix vars to avoid masking
MYAPP_PORT = "8080"
MYAPP_HOST = "localhost"

[profile]
# Use unique, prefixed function names
common = '''
  myapp_setup() { ... }
  myapp_debug() { ... }
'''

[services.myapp-db]  # Prefix service names
command = "..."
```

**Best practices for layerable environments:**
- Single responsibility per environment
- Expect vars/binaries might be overridden by upper layers
- Document what the environment provides/expects
- Keep hooks fast and idempotent
- Use prefixed names to avoid collisions

## Sharing, Composition & FloxHub

Beyond runtime **layering** (above), Flox environments can be **composed** at
build time and **shared** via Git or FloxHub.

### Core Concepts

- **Composition**: build-time merging of environments (deterministic), via `[include]`
- **Remote environments**: shared environment definitions via FloxHub
- **Team collaboration**: reusable, shareable environment stacks

### What Gets Shared

The `.flox/` directory contains the environment *definition*: package specs and
versions, environment variables, build definitions, hooks, and services. It does
**not** include built binaries/artifacts (those are published as packages — see
`references/publish.md`) or local data/cache.

Two sharing mechanisms:
1. **Git** — commit the `.flox/` directory, typically alongside source code in
   the same repo. Others clone and get both the environment and the source.
2. **FloxHub** — `flox push` shares ONLY the `.flox/` directory (no source).
   Useful for runtime environments or shared base environments used across
   multiple projects.

### Sharing & Remote Commands

```bash
flox push                                       # push local env definition to FloxHub
flox pull owner/environment-name                # pull a remote env to work on locally
flox activate -r owner/environment-name         # activate a remote env directly
flox activate -r owner/environment-name -- cmd  # ... and run a command
```

### Environment Composition (`[include]`)

Merge environments at build time:

```toml
[include]
environments = [
    { remote = "team/postgres" },
    { remote = "team/redis" },
    { remote = "team/python-base" }
]
```

Override composed values locally:

```toml
[include]
environments = [{ remote = "team/postgres" }, { remote = "team/redis" }]

[vars]
POSTGRES_HOST = "localhost"
POSTGRES_PORT = "5433"   # non-standard port
```

**Designing composable environments:**
- No overlapping vars, services, or function names — namespace everything
  (`postgres_init`, not `init`; `POSTGRES_PORT`, not `PORT`)
- Use `pkg-group` to prevent package conflicts
- Keep hook logic minimal and idempotent (composed envs run ALL hooks)
- Avoid auto-run/display logic in `[profile]` (runs once per composed env)
- Test each environment standalone (`flox activate`) before composing

Included environments are captured at their current version when you add
them — there is no inline version field. Pull later changes in with
`flox include upgrade` (all includes) or `flox include upgrade <name>` (one):

```toml
[include]
environments = [
    { remote = "team/base" },
    { remote = "team/tools" }
]
```

### Pushing & Pulling

```bash
# Push a local environment to FloxHub
git init && git add .flox/ && git commit -m "Initial environment"
flox push
# Others: flox activate -r yourusername/your-repo

# Pull a remote environment to work on locally
flox pull owner/environment-name
flox activate
```

**Choosing Git vs FloxHub:**
- **Commit `.flox/` to Git** when the environment is for development (build
  tools), lives alongside source, and you want version history with the code.
- **Push to FloxHub** when the environment is for runtime/production (no source),
  is a shared base used across projects, or must be versioned independently.
- **Recommended**: commit dev environments to Git with source; push runtime
  environments to FloxHub.

### Team Collaboration Patterns

**Base + specialization** — a shared base, composed into team environments:

```toml
# team/base
[install]
git.pkg-path = "git"
gh.pkg-path = "gh"
jq.pkg-path = "jq"
```

```toml
# team/frontend
[include]
environments = [{ remote = "team/base" }]
[install]
nodejs.pkg-path = "nodejs"
pnpm.pkg-path = "pnpm"
```

**Service libraries** — reusable service environments composed into projects:

```toml
# team/postgres-service
[install]
postgresql.pkg-path = "postgresql"

[services.postgres]
command = '''
  mkdir -p "$FLOX_ENV_CACHE/postgres"
  if [ ! -d "$FLOX_ENV_CACHE/postgres/data" ]; then
    initdb -D "$FLOX_ENV_CACHE/postgres/data"
  fi
  exec postgres -D "$FLOX_ENV_CACHE/postgres/data" \
    -h "$POSTGRES_HOST" -p "$POSTGRES_PORT"
'''

[vars]
POSTGRES_HOST = "localhost"
POSTGRES_PORT = "5432"
```

```toml
# my-project
[include]
environments = [
    { remote = "team/postgres-service" },
    { remote = "team/redis-service" }
]
```

**Development vs runtime environments:**
- **Development** (committed to Git with source): contains build tools and build
  definitions; teammates `git clone` + `flox activate` for the same dev setup.
- **Runtime** (pushed to FloxHub, no source): installs the *published* package
  (`myapp.pkg-path = "myorg/myapp"`) rather than building from source.

### Composition Troubleshooting

- **Conflicts between composed environments**: use different `pkg-group` values,
  adjust `priority` for file conflicts, namespace variables, and test each env
  standalone first.
- **Remote environment not found**: `flox pull owner/env`, then `flox list -c` to
  inspect.

