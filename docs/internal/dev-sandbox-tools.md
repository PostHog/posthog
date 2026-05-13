# Dev sandbox: per-user CLI tools

`./bin/sandbox` ships a fixed toolbox (uv, clickhouse, phrocs, rpk, claude-code,
etc.) baked into `Dockerfile.sandbox`. To add your own CLIs (`gh`, `gt`, etc.)
and carry your host auth files into each sandbox, configure
`~/.posthog-sandboxes/tools.yaml`. It's per user, not committed.

Two responsibilities, split cleanly:

- `install:` snippets bake into a per-user image layer on top of the team base.
  Built once per change to `tools.yaml`; cached afterwards. `sandbox create`
  reuses the cached image with zero install time at boot.
- `mounts:` are copied from host into the sandbox at boot, matching the existing
  Claude / gitconfig copy step. Snapshot semantics: each `sandbox create` picks
  up the current host state.

## Schema

```yaml
tools:
  - name: gh
    install: |
      GH_VERSION=2.92.0
      ARCH=$(dpkg --print-architecture)
      mkdir -p ~/.local
      curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${ARCH}.tar.gz" \
        | tar -xz --strip-components=1 -C ~/.local
    mounts:
      - ~/.config/gh

  - name: gt
    install: |
      npm install -g @withgraphite/graphite-cli@stable
    mounts:
      - ~/.config/graphite

  - name: somecli # long form: explicit target when source isn't under $HOME
    mounts:
      - source: /etc/somecli/config.toml
        target: ~/.config/somecli/config.toml
```

- `name` is required. `install` and `mounts` are independently optional; a
  tool that only declares `mounts` is valid (useful for wiring auth into a
  tool already in the base image).
- `install` is plain shell run as the sandbox user at image build time.
  It must not need root — install tools into the user's home (`~/.local`,
  `~/.npm-global` via `npm install -g`, `~/.cargo` via `cargo install`,
  etc.). Anything that genuinely needs system-wide install (`apt-get`,
  writes under `/usr`) belongs in the base `Dockerfile.sandbox`, not in
  a per-user recipe.
- Mount short form (string): host absolute path under `$HOME`, copied to the
  same `$HOME`-relative path inside the sandbox.
- Mount long form (`{source, target}`): use when source isn't under `$HOME`,
  or when you want a different in-sandbox target. `target` must resolve under
  the sandbox user's `$HOME`.
- Missing host sources are silently skipped, so you can list `~/.config/gh`
  before ever running `gh auth login`.

## `sandbox tools` subcommand

Don't edit `tools.yaml` by hand for the common case; the subcommand keeps you
out of trouble.

```bash
sandbox tools list                       # print configured tools + catalog
sandbox tools add <name>                 # interactive prompt (or catalog pick)
sandbox tools add <name> --install '...' # non-interactive (scripting)
sandbox tools remove <name>              # strip the entry
```

The interactive `add` flow optionally builds a throwaway test layer on top of
the current base image to verify your install snippet before saving it.

## Catalog of vetted recipes

`bin/sandbox-tools.yaml` is the checked-in catalog of pre-baked install +
mount recipes (`gh`, `gt`, etc.). When you run `sandbox tools add <name>` and
the name matches a catalog entry, the CLI shows the recipe, asks for
confirmation, and writes it straight into your `tools.yaml`. `sandbox tools
list` always prints the catalog so you can see what's available.

To contribute a new recipe, edit `bin/sandbox-tools.yaml`: add an entry with
`name`, a one-line `description`, an `install` shell snippet, and any
`mounts` the tool reads from the host. Run `sandbox tools add <name>
--install ... --test` locally first to confirm the snippet builds against
the current base image. Keep entries alphabetical by name for stable diffs.

## Image lifecycle

`bin/sandbox` builds two layers:

1. **Base image** `posthog-sandbox:base` from `Dockerfile.sandbox`. Tracked by
   a label that hashes the Dockerfile, the entrypoint, and the tmux config;
   automatically rebuilt when any of those change.
2. **Personal image** `posthog-sandbox-user:<hash>` from `tools.yaml`. Hash
   covers the base digest, your host UID/GID, and the YAML bytes. Each tool's
   install snippet is its own `RUN` layer, so appending a tool reuses prior
   layers and only the new RUN runs.

After each successful personal image build, `bin/sandbox` prunes
`posthog-sandbox-user:*` tags older than the three most recent (per user).

## Auth sync behavior

- Snapshot at create: each `sandbox create` copies the current host state for
  declared mounts. Running sandboxes don't auto pick up subsequent host changes.
  Destroy and recreate to refresh.
- One-way: the sandbox can never clobber host config.
- macOS Keychain caveat: tools that stash secrets in Keychain (rather than
  files) won't transfer. `gh` defaults to file-based auth, so this is rare.

## Editing layer order

Editing or removing a snippet in the middle of the list invalidates all later
layers (standard Docker behavior). If you're iterating on a snippet, keep it
at the end of `tools:` while developing it, then move it where you want once
it's stable.
