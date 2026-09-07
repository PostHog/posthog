# Opt-in devenv (devenv.sh) developer environment for PostHog.
#
# Installing devenv is the opt-in: .envrc activates this instead of flox once
# the binary is on PATH. Set POSTHOG_DEV_ENV=flox to go back to flox without
# uninstalling devenv. Nothing here reads or writes .flox/.
#
# This mirrors .flox/env/manifest.toml section by section: packages, the Rust
# and Go toolchains, the Node runtime, [vars], the on-activate hook (as tasks),
# and the parts of the [profile] scripts that a single enterShell can carry.
{ pkgs, lib, config, inputs, ... }:

let
  # The documented `multiverse` module argument forwards the rolling nixpkgs'
  # whole `pkgs.config` into the older pinned revisions, which reject it
  # (`problems.matchers.*.kind = "broken"` is not in their option type).
  # Building the multiverse by hand with a minimal config avoids that.
  # Observed on devenv 2.2.2.
  multiverse = inputs.nixpkgs-multiverse.lib.mkMultiverse {
    system = pkgs.stdenv.hostPlatform.system;
    config = { allowUnfree = true; };
  };

  # Solve all pins in one call. Cost is per nixpkgs revision touched, not per
  # package, so one solve groups these onto far fewer revisions than asking for
  # each version separately.
  pins = multiverse.solvePins {
    cmake = "3.31.5";
    emscripten = "4.0.23";
    ffmpeg_5 = "5.1.4";
    nodejs_24 = "24.13.0";
    openssl = "3.4.1";
    sqlx-cli = "0.8.3";
    uv = "0.11.14";
    xmlsec = "1.3.7";
  };

  # Node is handed to languages.javascript below rather than installed directly,
  # so it must not also land in `packages`.
  pinnedPackages = builtins.attrValues (builtins.removeAttrs pins [ "nodejs_24" ]);

  # Every task runs one subcommand of bin/devenv-tasks.sh before the shell opens,
  # so a task declaration only has to say which subcommand and what differs.
  mkTask = name: extra: {
    exec = "$DEVENV_ROOT/bin/devenv-tasks.sh ${name}";
    before = [ "devenv:enterShell" ];
  } // extra;
in
{
  # ---- packages ---------------------------------------------------------
  packages = pinnedPackages
    # devenv links the out, bin, lib, dev and include outputs of everything in
    # `packages` into one profile. `man` is not in that set, so ask for it by
    # name to keep `man openssl` working.
    ++ [ pins.openssl.man ]
    ++ (with pkgs; [
      # Python. Python itself is installed on activation by `uv sync`.
      freetds # for pymssql

      # Node
      brotli
      zstd
      nodemon

      # Rust. The toolchain, including rust-analyzer, comes from
      # languages.rust below.
      sccache

      # Go
      golangci-lint
      air

      # CLI tools
      git-lfs
      ripgrep
      mprocs
      util-linux # flock
      postgresql_14 # psql
      protobuf # protoc compiler for gRPC code generation
      ninja
      libpthread-stubs
      watchman # fast file watching for Django/Celery autoreload (uses pywatchman)
      trunk-io # launcher for the Trunk merge queue CLI; the CLI version itself is pinned in .trunk/trunk.yaml
    ])
    # node-rdkafka's librdkafka dlopens liblz4/libsasl2 at runtime on Linux; the
    # .so files live outside the default outputs.
    ++ lib.optionals pkgs.stdenv.isLinux (with pkgs; [
      lz4
      lz4.dev
      cyrus_sasl
      cyrus_sasl.dev
    ])
    ++ lib.optionals (pkgs.stdenv.isDarwin && pkgs.stdenv.isAarch64) (with pkgs; [
      libiconv
      lld # faster linker for Rust dev builds on macOS
    ])
    # `pkgs.go` tracks the rolling nixpkgs, which is ahead of the version the
    # repo builds against, so take the toolchain straight from go-overlay.
    ++ [ ((inputs.go-overlay.lib.mkGoBin pkgs).versions."1.25.5") ];

  # ---- Rust -------------------------------------------------------------
  # One option pins the whole toolchain coherently, which replaces the
  # rust-toolchain pkg-group in the flox manifest.
  languages.rust = {
    enable = true;
    channel = "stable";
    version = "1.91.1";
    components = [ "rustc" "cargo" "clippy" "rustfmt" "rust-src" "rust-analyzer" ];
  };

  # ---- Node -------------------------------------------------------------
  # corepack.enable puts a corepack shim for pnpm ahead of Node's own bin dir,
  # which is what the flox manifest gets from `corepack priority = 4`. Do not
  # add pnpm.enable: it installs nixpkgs' standalone pnpm, which ignores the
  # `packageManager` field in package.json.
  languages.javascript = {
    enable = true;
    package = pins.nodejs_24;
    corepack.enable = true;
  };

  # ---- env --------------------------------------------------------------
  env = {
    DEBUG = "1";
    POSTHOG_SKIP_MIGRATION_CHECKS = "1";
    FLAGS_REDIS_URL = "redis://localhost:6379/1";
    # ClickHouse client default DB. Matches the docker-compose convention.
    # Without it, Django queries unqualified `events` / `log_entries` etc.
    # resolve against the literal `default` DB (where PostHog has no tables)
    # and 500.
    CLICKHOUSE_DATABASE = "posthog";
    DIRENV_LOG_FORMAT = ""; # disable direnv activation logging
    DOTENV_FILE = ".env";
    RUSTC_WRAPPER = "sccache";

    # $DEVENV_PROFILE is one buildEnv symlink tree, the direct analogue of
    # $FLOX_ENV, so these keep the same merged-root shape as the flox manifest.
    OPENSSL_ROOT_DIR = "${config.devenv.profile}";
    OPENSSL_LIB_DIR = "${config.devenv.profile}/lib";
    OPENSSL_INCLUDE_DIR = "${config.devenv.profile}/include";
    LDFLAGS = "-L${config.devenv.profile}/lib";
    CPPFLAGS = "-I${config.devenv.profile}/include";

    # $DEVENV_STATE is the per-project state dir, the analogue of
    # $FLOX_ENV_CACHE. Keeping the venv and the Go caches there means a host Go
    # or Python install cannot poison builds, and `devenv gc` reclaims them.
    UV_PROJECT_ENVIRONMENT = "${config.devenv.state}/venv";
    GOTOOLCHAIN = "local";
    GOPATH = "${config.devenv.state}/go";
    GOCACHE = "${config.devenv.state}/go-build";
    GOMODCACHE = "${config.devenv.state}/go/pkg/mod";
  };

  # ---- tasks ------------------------------------------------------------
  # The flox hook runs once per activation. devenv's enterShell runs on every
  # entry, so the same work lives in tasks that run before devenv:enterShell and
  # skip themselves when their inputs are unchanged. The bodies are in
  # bin/devenv-tasks.sh so both environments keep one copy of each step.
  #
  # `status` and `execIfModified` are mutually exclusive in devenv, so each task
  # picks one.
  tasks = {
    "posthog:uv-sync" = mkTask "uv-sync" {
      description = "Install Python packages and expose hogli";
      execIfModified = [ "uv.lock" "pyproject.toml" ];
    };

    "posthog:pnpm-install" = mkTask "pnpm-install" {
      description = "Install Node packages";
      execIfModified = [ "pnpm-lock.yaml" "package.json" ];
    };

    "posthog:phrocs-build" = mkTask "phrocs-build" {
      description = "Build phrocs";
      execIfModified = [ "tools/phrocs" ];
    };

    # git-config has to land before pnpm install, because husky's `prepare` runs
    # there and its own core.hooksPath write is denied by the dev sandbox.
    "posthog:bootstrap" = mkTask "bootstrap" {
      description = "Seed git settings, create .env, check /etc/hosts";
      before = [ "devenv:enterShell" "posthog:pnpm-install" ];
      showOutput = true;
    };
  };

  # ---- enterShell -------------------------------------------------------
  # The flox [profile] equivalent. devenv has no per-shell profile, so anything
  # that has to be a shell function or a zsh completion cannot be set up from
  # here: run `source bin/phw` for the worktree helper and add
  # $DEVENV_STATE/completions to your own fpath for hogli completions.
  enterShell = ''
    # User shells often export GOROOT for a Homebrew or asdf Go install, which
    # would override the pinned toolchain.
    unset GOROOT

    # Share a single Cargo target dir so worktrees skip redundant linking.
    export CARGO_TARGET_DIR="$HOME/.cargo/target"

    # The install tasks only fire when their lockfiles change, so anything that
    # was deleted by hand (`hogli nuke`) is rebuilt here instead.
    if [ ! -f "$UV_PROJECT_ENVIRONMENT/bin/activate" ]; then
      "$DEVENV_ROOT/bin/devenv-tasks.sh" uv-sync
    fi
    if [ ! -d "$DEVENV_ROOT/node_modules/.pnpm" ]; then
      "$DEVENV_ROOT/bin/devenv-tasks.sh" pnpm-install
    fi
    if [ -f "$UV_PROJECT_ENVIRONMENT/bin/activate" ]; then
      . "$UV_PROJECT_ENVIRONMENT/bin/activate"
      export PATH="$UV_PROJECT_ENVIRONMENT/bin:$PATH"
    fi

    # posthog:phrocs-build can finish before the venv exists, so link the built
    # binary here rather than ordering the two tasks against each other.
    if [ -f "$DEVENV_ROOT/tools/phrocs/dist/phrocs" ] && [ -d "$UV_PROJECT_ENVIRONMENT/bin" ]; then
      ln -sf "$DEVENV_ROOT/tools/phrocs/dist/phrocs" "$UV_PROJECT_ENVIRONMENT/bin/phrocs"
    fi

    if [ -f "$DEVENV_ROOT/$DOTENV_FILE" ] && [ "''${POSTHOG_SKIP_DOTENV:-}" != "1" ]; then
      set -o allexport
      # shellcheck disable=SC1090
      . "$DEVENV_ROOT/$DOTENV_FILE"
      set +o allexport
    fi

    echo "PostHog dev (devenv) -- $(git -C "$DEVENV_ROOT" branch --show-current 2>/dev/null || echo '???')"
  '';
}
