# Flox in CI

Guidance for running CI steps inside a Flox environment, with GitHub Actions as
the worked example. The distinction that matters most: **installing Flox and
activating an environment are two separate things**, and only one action does
each.

## Install is not activation

| Action | What it does | What it does not do |
|---|---|---|
| [`flox/install-flox-action`](https://github.com/flox/install-flox-action) | Installs the Flox CLI on Linux and macOS runners | Does not activate a project environment. It has no input for running a command inside one. |
| [`flox/activate-action`](https://github.com/flox/activate-action) | Runs one command inside a local or remote Flox environment | Does not install Flox. Run the install action first. |

After `install-flox-action`, `flox` is on `PATH` — but the subsequent steps are
still running on the bare runner. Anything the environment provides
(interpreters, linters, services) is not there until something activates.

**On GitHub Actions, install with the action rather than the install script.**
The action is the supported integration, and you pin it to a commit SHA. The
script (`curl -fsSL https://get.flox.dev | sh`) is the right answer on
platforms with no official integration — see
[Other CI systems](#other-ci-systems).

## Short commands: `activate-action`

```yaml
- uses: flox/install-flox-action@1128abd73431089ab9d871c893b4e72a729354e1 # v2.6.0

- name: Run tests
  uses: flox/activate-action@7065dcbe5583b7b015f07a8ebd49d7266e3053e8 # v1.1.1
  with:
    command: python3 -m pytest -q
```

Inputs:

| Input | Required | Meaning |
|---|---|---|
| `command` | yes | The command to run inside the environment |
| `environment` | no | A remote environment (`owner/name`), passed as `-r=`. Omit to use the local `.flox/` |
| `dir` | no | Path containing the `.flox/` directory, passed as `--dir=` |

**Caveat — never build `command` from untrusted input, and keep it short.**
The action's `runs:` block interpolates the input into a single-quoted
`flox activate … -c '<command>'`. `environment` and `dir` are interpolated on
that same line **unquoted**.

That makes this a command-injection sink, not just a quoting nuisance. A single
quote in the value closes the wrapper and everything after it is read as shell:
a `command` built from `${{ github.event.pull_request.title }}` with the value
`a'; id; echo PWNED; 'x` runs `id` and `echo PWNED` as separate commands on the
runner. GitHub names PR titles and bodies, branch names, and review comments as
attacker-controlled contexts. Never interpolate any of them into `command`,
`environment`, or `dir`; pass them through `env:` and reference the variable
instead.

The same mechanism bites benign scripts by accident: `awk '{print $1}'`,
`bash -c 'x'`, and an apostrophe in an echoed message all terminate the
wrapper. Keep `command` to a short, quote-free invocation; for anything longer,
use the custom shell below.

## Multiline scripts: Flox as the step's shell

For a substantial multiline script, make Flox the shell so GitHub's generated
script runs entirely inside the environment:

```yaml
- name: Run checks
  shell: flox activate -- bash --noprofile --norc -e -o pipefail {0}
  run: |
    python3 -m pytest -q
    ruff check .
    mypy src
```

GitHub substitutes the path of the script it generated for `{0}`. One
activation covers the whole block.

Each flag earns its place:

- `--noprofile --norc` — mirror GitHub's own default shell invocation,
  `bash --noprofile --norc -eo pipefail {0}`, so replacing the default shell
  changes nothing about startup behaviour. (Bash given a script file, which
  `{0}` is, is neither interactive nor a login shell, so it would not read
  those files anyway. The flags document the intent and keep the two
  invocations identical.)
- `-e` — fail the step on the first failing command. Without it a custom shell
  reports success as long as the last line succeeded.
- `-o pipefail` — fail on a failing command anywhere in a pipeline, not just the
  last one.

**Do not repeat activation per line:**

```yaml
# WRONG — re-enters the environment three times, and each line loses any
# state the previous one set.
- name: Run checks
  run: |
    flox activate -- python3 -m pytest -q
    flox activate -- ruff check .
    flox activate -- mypy src
```

## Complete workflow

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2

      - name: Install Flox
        uses: flox/install-flox-action@1128abd73431089ab9d871c893b4e72a729354e1 # v2.6.0

      - name: Run checks
        shell: flox activate -- bash --noprofile --norc -e -o pipefail {0}
        run: |
          python3 -m pytest -q
          ruff check .
          mypy src
```

`shell:` is a step-level key, so mixed workflows are fine: steps that need the
environment carry it, steps that do not (uploading an artifact, posting a
comment) run on the default shell.

## Setting the shell once per job

If most steps in a job need the environment, set it as the job default and
override on the exceptions:

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        shell: flox activate -- bash --noprofile --norc -e -o pipefail {0}
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
      - uses: flox/install-flox-action@1128abd73431089ab9d871c893b4e72a729354e1 # v2.6.0
      - run: python3 -m pytest -q
```

Note the ordering constraint: `defaults.run.shell` applies to every `run:` step
in the job, including any that precede the install step. Keep pre-install work
in `uses:` steps, or set the shell per step instead.

## Remote environments

To run against a FloxHub environment rather than the repo's `.flox/`:

```yaml
- name: Run tests
  uses: flox/activate-action@7065dcbe5583b7b015f07a8ebd49d7266e3053e8 # v1.1.1
  with:
    environment: myorg/ci-tools
    command: python3 -m pytest -q
```

The custom-shell equivalent is `shell: flox activate -r myorg/ci-tools -- bash --noprofile --norc -e -o pipefail {0}`.
A remote environment that is not already trusted must be listed in
`install-flox-action`'s `trusted-environments` input. Trust is not credentials:
a private FloxHub environment also needs `FLOX_FLOXHUB_TOKEN` in the step's
`env:`, the same way `references/publish.md` passes it.

## Pinning

Where repository policy requires it — and it does in `flox/flox-skills` — pin
every third-party action to a full commit SHA with the version in a trailing
comment:

```yaml
- uses: flox/install-flox-action@1128abd73431089ab9d871c893b4e72a729354e1 # v2.6.0
```

A moving tag (`@v2`, `@main`) is a supply-chain hole: the tag can be repointed
at any commit. The SHA cannot.

**Look the SHA up; never invent one.** Forty plausible hex characters are easy
to produce and impossible to eyeball, and a wrong one fails the workflow at
`uses:` resolution with nothing pointing at the cause. Read it off the action's
releases page, or:

```bash
git ls-remote --tags https://github.com/flox/install-flox-action.git | grep v2.6.0
```

Make the trailing comment name the tag the SHA actually carries. A pin resolved
from `v6` and commented `# v6` goes stale the moment that moving tag advances,
which is the failure this section exists to prevent.

## Common mistakes

| Mistake | Why it fails | Fix |
|---|---|---|
| Treating `install-flox-action` as activation | It installs the CLI only; later steps run on the bare runner | Add `activate-action` or the custom `shell:` |
| `flox activate --` on every line of one `run:` block | Re-enters the environment per command; per-line state is lost | One `shell:` on the step |
| A multiline script in `activate-action`'s `command:` | Interpolated into `-c '…'`; an embedded `'` breaks the wrapper | Use the custom `shell:` |
| Custom shell without `-e -o pipefail` | Step passes as long as the last line passes | Keep both flags |
| Custom shell without `--noprofile --norc` | Diverges from GitHub's default shell invocation for no reason | Keep both flags |
| The install script in a GitHub Actions job | Works, but bypasses the supported SHA-pinned integration | `flox/install-flox-action` |
| `uses: flox/install-flox-action@v2` | Moving tag; supply-chain risk | Pin the full SHA |
| A made-up 40-character SHA | Fails at `uses:` resolution, and looks correct | Read it from the releases page or `git ls-remote` |

## Build and publish jobs

This file covers running CI steps *inside* an environment. Two related jobs
have their own references: a `flox build <target>` verification job (which
needs no activation at all) is specified in `references/builds.md` § The Build
Job Travels With the Target, and publishing from CI in `references/publish.md`
§ Continuous Integration Publishing.

## Other CI systems

GitHub Actions is this file's worked example, not a recommendation — a repo's
existing CI system is the one to integrate with. The official integrations:

| System | Integration |
|---|---|
| GitHub Actions | `flox/install-flox-action` + `flox/activate-action` (above) |
| CircleCI | The `flox/orb` orb — `flox/install` and `flox/activate` steps |
| GitLab CI | Run jobs in the `ghcr.io/flox/flox` container image; plain `flox` CLI commands from there |

Community integrations exist for other systems (e.g. Buildkite plugins) —
unofficial, so read the plugin before recommending it, and prefer the generic
pattern below when in doubt.

For anything else, the same install-is-not-activation split applies. Bake Flox
into the runner image where you control it, so job time is spent on the job
rather than on a download. Where the image is not yours to change,
`curl -fsSL https://get.flox.dev | sh` as the first job step is the supported
fallback.

Then enter the environment once per script rather than per line —
`flox activate -- <interpreter> <script>`, or by making the script's first
action an activation.
