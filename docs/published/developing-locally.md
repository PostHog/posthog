---
title: Developing locally
sidebar: Docs
showTitle: true
---
> ❗️ This guide is intended only for development of PostHog itself. If you're looking to deploy PostHog
> for your product analytics needs, go to [Self-host PostHog](/docs/self-host).

## What does PostHog look like on the inside?

Before jumping into setup, let's dissect a PostHog.

The app itself is made up of 4 main components that run simultaneously:

- Celery worker (handles execution of background tasks)
- Django server
- Node.js plugin server (handles event ingestion and apps/plugins)
- React frontend built with Node.js

We also have a growing collection of Rust services that handle performance-critical operations:

- capture – receives HTTP event capture requests and extracts event payloads
- feature-flags – handles feature flag evaluation
- cymbal – processes source maps for error tracking
- property-defs-rs – extracts and infers property definitions from events
- hook services – manages webhooks with high performance
- hogvm – evaluates HogQL bytecode via a stack machine implementation

These components rely on a few external services:

- ClickHouse – for storing big data (events, persons – analytics queries)
- Kafka – for queuing events for ingestion
- MinIO – for storing files (session recordings, file exports)
- PostgreSQL – for storing ordinary data (users, projects, saved insights)
- Redis – for caching and inter-service communication
- Zookeeper – for coordinating Kafka and ClickHouse clusters

When spinning up an instance of PostHog for development, we recommend the following configuration:

- the external services run in Docker over `docker compose`
- PostHog itself runs on the host (your system)

This is what we'll be using in the guide below.

> It is also technically possible to run PostHog in Docker completely, but syncing changes is then much slower, and for development you need PostHog dependencies installed on the host anyway (such as formatting or typechecking tools).
> The other way around – everything on the host, is not practical due to significant complexities involved in instantiating Kafka or ClickHouse from scratch.

The instructions here assume you're running macOS or the current Ubuntu Linux LTS (24.04).

For other Linux distros, adjust the steps as needed (e.g. use `dnf` or `pacman` in place of `apt`).

Windows isn't supported natively. But, Windows users can run a Linux virtual machine. The latest Ubuntu LTS Desktop is recommended. (Ubuntu Server is not recommended as debugging the frontend will require a browser that can access localhost.)

In case some steps here have fallen out of date, please tell us about it – feel free to [submit a patch](https://github.com/PostHog/posthog.com/blob/master/contents/handbook/engineering/developing-locally.md)!

## Option 1: Developing with Codespaces

This is a faster option to get up and running. If you don't want to or can't use Codespaces, continue from the next section.

1. Create your codespace.
![](https://user-images.githubusercontent.com/890921/231489405-cb2010b4-d9e3-4837-bfdf-b2d4ef5c5d0b.png)
2. Update it to 8-core machine type (the smallest is probably too small to get PostHog running properly).
![](https://user-images.githubusercontent.com/890921/231490278-140f814e-e77b-46d5-9a4f-31c1b1d6956a.png)
3. Open the codespace, using one of the "Open in" options from the list.
4. In the codespace, open a terminal window and run `docker compose -f docker-compose.dev.yml up`.
5. Ensure that you are using the right Node version (`nvm install 22 && nvm use 22`) then, in another terminal, run `pnpm i` (and use the same terminal for the following commands).
6. Then run `uv sync`
    - If this doesn't activate your python virtual environment, run `uv venv` (install `uv` following instructions [here](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer) if needed)
7. Install `sqlx-cli` with `cargo install sqlx-cli` (install Cargo following instructions [here](https://doc.rust-lang.org/cargo/getting-started/installation.html) if needed)
8. Now run `DEBUG=1 ./bin/migrate`
9. Install [mprocs](https://github.com/pvolok/mprocs#installation) (`cargo install mprocs`)
10. Run `./bin/start`.
11. Open browser to <http://localhost:8010/>.
12. To get some practical test data into your brand-new instance of PostHog, run `DEBUG=1 ./manage.py generate_demo_data`.

## Option 2: Developing locally

### Prerequisites

#### macOS

1. Install Xcode Command Line Tools if you haven't already: `xcode-select --install`.

2. Install the package manager Homebrew by following the [instructions here](https://brew.sh/).

    <blockquote class="warning-note">
        After installation, make sure to follow the instructions printed in your terminal to add Homebrew to your{' '}
        <code>$PATH</code>. Otherwise the command line will not know about packages installed with <code>brew</code>.
    </blockquote>

3. Install [OrbStack](https://orbstack.dev/) – a more performant Docker Desktop alternative – with `brew install orbstack`. Go to OrbStack settings and set the memory usage limit to **at least 4 GB** (or 8 GB if you can afford it) + the CPU usage limit to at least 4 cores (i.e. 400%). You'll want to use Brex for the license if you work at PostHog.

4. Continue with [cloning the repository](#cloning-the-repository).

#### Ubuntu

> Note: Importantly, if you're internal to PostHog we are standardised on working on MacOS (not Linux). In part because of SOC2 auditing gains it gives us.

1. Install Docker following [the official instructions here](https://docs.docker.com/engine/install/ubuntu/).

2. Install the `build-essential` package:

    ```bash
    sudo apt install -y build-essential
    ```

3. Continue with [cloning the repository](#cloning-the-repository).

#### Cloning the repository

Clone the [PostHog repo](https://github.com/posthog/posthog). All future commands assume you're inside the `posthog/` folder.

```bash
git clone https://github.com/PostHog/posthog && cd posthog/
```

> The `feature-flags` container relies on the presence of the GeoLite cities
> database in the `/share` directory. If you haven't run `./bin/start` this database may not exist.
> You can explicitly download it by running `./bin/download-mmdb`. You may also need to modify the
> file permissions of the database with:
>
> `chmod 0755 ./share/GeoLite2-City.mmdb`

### Instant setup

You can set your development environment up instantly using [Flox](https://flox.dev/).

Flox is a development environment manager – it ensures we all have the same right system-level dependencies when developing PostHog. It's pretty much an npm for runtimes and libraries: `.flox/env/manifest.toml` is like `package.json`, `.flox/env/manifest.lock` is akin to `package-lock.json`, and `.flox/cache/` resembles `node_modules/`.

To get PostHog running in a dev environment:

1. Once you have cloned the repo and installed OrbStack, now install Flox (plus `ruff` and `rustup` for pre-commit checks outside the Flox env).

    ```bash
    brew install flox ruff rustup && rustup-init && rustup default stable
    ```

2. From the root of the repository, activate the environment. (On first activation, you'll be prompted if you'd like the environment to be activated automatically using `direnv`.)

    ```bash
    flox activate
    ```

    This gets you a fully fledged environment, with linked packages stored under `.flox/`. Might take a moment to run the first time, as dependencies get downloaded.

    > Note on app dependencies: Python requirements get updated every time the environment is activated (`uv sync` is lightning fast). JS dependencies only get installed if `node_modules/` is not present (`pnpm install` still takes a couple lengthy seconds). Dependencies for other languages currently don't get auto-installed.

3. After successful environment activation, just look at its welcome message in the terminal. It contains all the commands for running the stack. Run those commands in the suggested order.

This is it – you should be seeing the PostHog app at <a href="http://localhost:8010" target="_blank">http://localhost:8010</a>.

You can now change PostHog in any way you want. See [Project structure](/handbook/engineering/project-structure) for an intro to the repository's contents. To commit changes, create a new branch based on `master` for your intended change, and develop away.

### Manual setup

Alternatively, if you'd prefer not to use [Flox-based instant setup](#instant-setup), you can set the environment up manually:

#### 1. Spin up external services

In this step we will start all the external services needed by PostHog to work.

First, append line `127.0.0.1 kafka clickhouse clickhouse-coordinator objectstorage` and line `::1 kafka clickhouse clickhouse-coordinator objectstorage` to `/etc/hosts`. Our ClickHouse and Kafka data services won't be able to talk to each other without these mapped hosts.
You can do this with:

```bash
echo '127.0.0.1 kafka clickhouse clickhouse-coordinator objectstorage' | sudo tee -a /etc/hosts
echo '::1 kafka clickhouse clickhouse-coordinator objectstorage' | sudo tee -a /etc/hosts
```

> If you are using a newer (>=4.1) version of Podman instead of Docker, the host machine's `/etc/hosts` is used as the base hosts file for containers by default, instead of container's `/etc/hosts` like in Docker. This can make hostname resolution fail in the ClickHouse container, and can be mended by setting `base_hosts_file="none"` in [`containers.conf`](https://github.com/containers/common/blob/main/docs/containers.conf.5.md#containers-table).

Now, start the Docker Compose stack:

```bash
docker compose -f docker-compose.dev.yml up
```

> **Friendly tip 1:** If you see `Error while fetching server API version: 500 Server Error for http+docker://localhost/version:`, it's likely that Docker Engine isn't running.

> **Friendly tip 2:** If you see "Exit Code 137" anywhere, it means that the container has run out of memory. In this case you need to allocate more RAM in OrbStack settings.

> **Friendly tip 3:** On Linux, you might need `sudo` – see [Docker docs on managing Docker as a non-root user](https://docs.docker.com/engine/install/linux-postinstall). Or look into [Podman](https://podman.io/getting-started/installation) as an alternative that supports rootless containers.

>**Friendly tip 4:** If you see `Error: (HTTP code 500) server error - Ports are not available: exposing port TCP 0.0.0.0:5432 -> 0.0.0.0:0: listen tcp 0.0.0.0:5432: bind: address already in use`, you have Postgres already running somewhere. Try `docker compose -f docker-compose.dev.yml` first, alternatively run `lsof -i :5432` to see what process is using this port.

```bash
sudo service postgresql stop
```

Second, verify via `docker ps` and `docker logs` (or via the OrbStack dashboard) that all these services are up and running. They should display something like this in their logs:

```shell
# docker ps                                                                                     NAMES
CONTAINER ID   IMAGE                                      COMMAND                  CREATED          STATUS                    PORTS                                                                                            NAMES
5a38d4e55447   temporalio/ui:2.10.3                       "./start-ui-server.sh"   51 seconds ago   Up 44 seconds             0.0.0.0:8081->8080/tcp                                                                           posthog-temporal-ui-1
89b969801426   temporalio/admin-tools:1.20.0              "tail -f /dev/null"      51 seconds ago   Up 44 seconds                                                                                                              posthog-temporal-admin-tools-1
81fd1b6d7b1b   clickhouse/clickhouse-server:23.6.1.1524   "/entrypoint.sh"         51 seconds ago   Up 50 seconds             0.0.0.0:8123->8123/tcp, 0.0.0.0:9000->9000/tcp, 0.0.0.0:9009->9009/tcp, 0.0.0.0:9440->9440/tcp   posthog-clickhouse-1
f876f8bff35f   bitnami/kafka:2.8.1-debian-10-r99          "/opt/bitnami/script…"   51 seconds ago   Up 50 seconds             0.0.0.0:9092->9092/tcp                                                                           posthog-kafka-1
d22559261575   temporalio/auto-setup:1.20.0               "/etc/temporal/entry…"   51 seconds ago   Up 45 seconds             6933-6935/tcp, 6939/tcp, 7234-7235/tcp, 7239/tcp, 0.0.0.0:7233->7233/tcp                         posthog-temporal-1
5313fc278a70   postgres:12-alpine                         "docker-entrypoint.s…"   51 seconds ago   Up 50 seconds (healthy)   0.0.0.0:5432->5432/tcp                                                                           posthog-db-1
c04358d8309f   zookeeper:3.7.0                            "/docker-entrypoint.…"   51 seconds ago   Up 50 seconds             2181/tcp, 2888/tcp, 3888/tcp, 8080/tcp                                                           posthog-zookeeper-1
09add699866e   maildev/maildev:2.0.5                      "bin/maildev"            51 seconds ago   Up 50 seconds (healthy)   0.0.0.0:1025->1025/tcp, 0.0.0.0:1080->1080/tcp                                                   posthog-maildev-1
61a44c094753   elasticsearch:7.16.2                       "/bin/tini -- /usr/l…"   51 seconds ago   Up 50 seconds             9200/tcp, 9300/tcp                                                                               posthog-elasticsearch-1
a478cadf6911   minio/minio:RELEASE.2022-06-25T15-50-16Z   "sh -c 'mkdir -p /da…"   51 seconds ago   Up 50 seconds             9000/tcp, 0.0.0.0:19000-19001->19000-19001/tcp                                                   posthog-object_storage-1
91f838afe40e   redis:6.2.7-alpine                         "docker-entrypoint.s…"   51 seconds ago   Up 50 seconds             0.0.0.0:6379->6379/tcp                                                                           posthog-redis-1

# docker logs posthog-db-1 -n 1
2021-12-06 13:47:08.325 UTC [1] LOG:  database system is ready to accept connections

# docker logs posthog-redis-1 -n 1
1:M 06 Dec 2021 13:47:08.435 * Ready to accept connections

# docker logs posthog-clickhouse-1 -n 1
Saved preprocessed configuration to '/var/lib/clickhouse/preprocessed_configs/users.xml'.

# ClickHouse writes logs to `/var/log/clickhouse-server/clickhouse-server.log` and error logs to `/var/log/clickhouse-server/clickhouse-server.err.log` instead of stdout/stsderr. It can be useful to `cat` these files if there are any issues:
# docker exec posthog-clickhouse-1 cat /var/log/clickhouse-server/clickhouse-server.log
# docker exec posthog-clickhouse-1 cat /var/log/clickhouse-server/clickhouse-server.err.log

# docker logs posthog-kafka-1
[2021-12-06 13:47:23,814] INFO [KafkaServer id=1001] started (kafka.server.KafkaServer)

# docker logs posthog-zookeeper-1
# Because ClickHouse and Kafka connect to Zookeeper, there will be a lot of noise here. That's good.
```

> **Friendly tip 1:** Kafka is currently the only x86 container used, and might segfault randomly when running on ARM. Restart it when that happens.

> **Friendly tip 2:** Checking the last Clickhouse log could show a `get_mempolicy: Operation not permitted` message. However, it shouldn't affect the app startup - checking the whole log should clarify that Clickhouse started properly. To double-check you can get into the container and run a basic query.
>
> ```bash
> # docker logs posthog-clickhouse-1
> # docker exec -it posthog-clickhouse-1 bash
> # clickhouse-client --query "SELECT 1"

Finally, install Postgres locally. Even if you are planning to run Postgres inside Docker, we need a local copy of Postgres (version 11+) for its CLI tools and development libraries/headers. These are required by `pip` to install `psycopg2`.

- On macOS:

    ```bash
    brew install postgresql
    ```

This installs both the Postgres server and its tools. DO NOT start the server after running this.

- On Debian-based Linux:

    ```bash
    sudo apt install -y postgresql-client postgresql-contrib libpq-dev
    ```

This intentionally only installs the Postgres client and drivers, and not the server. If you wish to install the server, or have it installed already, you will want to stop it, because the TCP port it uses conflicts with the one used by the Postgres Docker container.

On Linux, it's recommended to disable Postgres service by default, to ensure no port conflict arises. If `postgres` is already running on the port `5432`, you can confirm it by checking the port, and then kill it manually.

```bash
sudo systemctl disable postgresql.service
sudo lsof -i :5432
sudo kill -9 `sudo lsof -t -i :5432`
```

On Linux you often have separate packages: `postgres` for the tools, `postgres-server` for the server, and `libpostgres-dev` for the `psycopg2` dependencies. Consult your distro's list for an up-to-date list of packages.

#### 2. Prepare the frontend

1. Install nvm, with `brew install nvm` or by following the instructions at <https://github.com/nvm-sh/nvm>. If using fish, you may instead prefer <https://github.com/jorgebucaran/nvm.fish>.

<blockquote class="warning-note">
    After installation, make sure to follow the instructions printed in your terminal to add NVM to your{' '}
    <code>$PATH</code>. Otherwise the command line will use your system Node.js version instead.
</blockquote>

2. Install the latest Node.js 22 (the version used by PostHog in production) with `nvm install 22`. You can start using it in the current shell with `nvm use 22`.

3. Install pnpm by running `corepack enable` and then running `corepack prepare pnpm@9 --activate`. Validate the installation with `pnpm --version`.

4. Install Node packages by running `pnpm i`.

5. Run `pnpm --filter=@posthog/frontend typegen:write` to generate types for [Kea](https://keajs.org/) state management logics used all over the frontend.

> The first time you run typegen, it may get stuck in a loop. If so, cancel the process (`Ctrl+C`), discard all changes in the working directory (`git reset --hard`), and run `pnpm typegen:write` again. You may need to discard all changes once more when the second round of type generation completes.

#### 3. Prepare plugin server

1. Install the `brotli` compression library and `rust` stable via `rustup`:

- On macOS:

    ```bash
    brew install brotli rustup
    rustup default stable
    rustup-init
    # Select 1 to proceed with default installation
    ```

- On Debian-based Linux:

    ```bash
    sudo apt install -y brotli
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
    # Select 1 to proceed with default installation
    ```

2. Run `pnpm --filter=@posthog/plugin-server install` to install all required packages. We'll actually run the plugin server in a later step.

> **Note:** If you face an error like `ld: symbol(s) not found for architecture arm64`, most probably your openssl build flags are coming from the wrong place. To fix this, run:

```bash
export CPPFLAGS=-I/opt/homebrew/opt/openssl/include
export LDFLAGS=-L/opt/homebrew/opt/openssl/lib
pnpm --filter=@posthog/plugin-server install
```

> **Note:** If you face an error like `import gyp  # noqa: E402`, most probably need to install `python-setuptools`. To fix this, run:

```bash
brew install python-setuptools
```

> **Troubleshooting plugin server issues:** If you encounter problems starting up the plugin server, try these debugging steps:

```bash
cd plugin-server
pnpm rebuild
pnpm i
```

#### 4. Prepare the Django server

1. Install a few dependencies for SAML to work. If you're on macOS, run the command below, otherwise check the official [xmlsec repo](https://github.com/mehcode/python-xmlsec) for more details.

    - On macOS:

        ```bash
        brew install libxml2 libxmlsec1 pkg-config
        ```

        > If installing `xmlsec` doesn't work, try updating macOS to the latest version (Sonoma).

    - On Debian-based Linux:

        ```bash
        sudo apt install -y libxml2 libxmlsec1-dev libffi-dev pkg-config
        ```

1. Install Python 3.11.

    - On macOS, you can do so with Homebrew: `brew install python@3.11`.

    - On Debian-based Linux:

        ```bash
        sudo add-apt-repository ppa:deadsnakes/ppa -y
        sudo apt update
        sudo apt install python3.11 python3.11-venv python3.11-dev -y
        ```

Make sure when outside the venv to always use `python3` instead of `python`, as the latter may point to Python 2.x on some systems. If installing multiple versions of Python 3, such as by using the `deadsnakes` PPA, use `python3.11` instead of `python3`.

You can also use [pyenv](https://github.com/pyenv/pyenv) if you wish to manage multiple versions of Python 3 on the same machine.

1. Install `uv`

`uv` is a very fast tool you can use for python virtual env and dependency management. See [https://docs.astral.sh/uv/](https://docs.astral.sh/uv/). Once installed you can prefix any `pip` command with `uv` to get the speed boost.

1. Create the virtual environment with the right Python version, and install dependencies - all in one with this command:

    ```bash
    uv sync
    ```

   > **Friendly tip:** Creating an env could raise a `Failed to parse` warning related to `pyproject.toml`. However, you should still see the `Activate with:` line at the very end, which means that your env was created successfully.

1. Activate the virtual environment:

    ```bash
    # For bash/zsh/etc.
    source .venv/bin/activate

    # For fish
    source .venv/bin/activate.fish
    ```

1. Install requirements with uv

    If your workstation is an Apple Silicon Mac, the first time you install Python packages, you must set custom OpenSSL headers:

    ```bash
    brew install openssl
    CFLAGS="-I /opt/homebrew/opt/openssl/include $(python3.11-config --includes)" LDFLAGS="-L /opt/homebrew/opt/openssl/lib" GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1 GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1 uv sync
    ```

    > **Friendly tip:** If you see `ERROR: Could not build wheels for xmlsec`, refer to this [issue](https://github.com/xmlsec/python-xmlsec/issues/254).

    These will be used when installing `grpcio` and `psycopg2`. After doing this once, and assuming nothing changed with these two packages, next time simply run:

    ```bash
    uv sync
    ```

#### 5. Prepare databases

We now have the backend ready, and Postgres and ClickHouse running – these databases are blank slates at the moment however, so we need to run _migrations_ to e.g. create all the tables:

```bash
cargo install sqlx-cli # If you haven't already
DEBUG=1 ./bin/migrate
```

> **Friendly tip 1:** The error `fe_sendauth: no password supplied` connecting to Postgres happens when the database is set up with a password and the user:pass isn't specified in `DATABASE_URL`. Try `export DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog`.

> **Friendly tip 2:** You may run into `psycopg2` errors while migrating on an ARM machine. Try out the steps in this [comment](https://github.com/psycopg/psycopg2/issues/1216#issuecomment-820556849) to resolve this.

> **Friendly tip 3:** When migrating, make sure the containers are running (detached or in a separate terminal tab).

#### 6. Start PostHog

Now start all of PostHog (backend, worker, plugin server, and frontend – simultaneously) with one of:

```bash
./bin/start

# only services strictly required to run posthog
./bin/start --minimal

# if you want to log additionally each process to a /tmp/posthog-<process-name>.log file for AI code editors to be able to grep
./bin/start --custom bin/mprocs-with-logging.yaml
```

> **Note:** This command uses [mprocs](https://github.com/pvolok/mprocs) to run all development processes in a single terminal window. It will be installed automatically for macOS, while for Linux you can install it manually (`cargo` or `npm`) using the official repo guide.

> **Friendly tip:** If you get the error `Configuration property "enable.ssl.certificate.verification" not supported in this build: OpenSSL not available at build time`, make sure your environment is using the right `openssl` version by setting [those](https://github.com/xmlsec/python-xmlsec/issues/261#issuecomment-1630889826) environment variables, and then run `./bin/start` again.

Open [http://localhost:8010](http://localhost:8010) to see the app.

> **Note:** The first time you run this command you might get an error that says "layout.html is not defined". Make sure you wait until the frontend is finished compiling and try again.

To get some practical test data into your brand-new instance of PostHog, run `DEBUG=1 ./manage.py generate_demo_data`. For a list of useful arguments of the command, run `DEBUG=1 ./manage.py generate_demo_data --help`.

> **Friendly Tip** The first time you run the app, you can log in with a test account: _user_:`test@posthog.com` _pwd_:`12345678`.

#### 7. Develop

This is it – you should be seeing the PostHog app at <a href="http://localhost:8010" target="_blank">http://localhost:8010</a>.

You can now change PostHog in any way you want. See [Project structure](/handbook/engineering/project-structure) for an intro to the repository's contents. To commit changes, create a new branch based on `master` for your intended change, and develop away.

## Testing

For a PostHog PR to be merged, all tests must be green, and ideally you should be introducing new ones as well – that's why you must be able to run tests with ease.

### Frontend

For frontend unit tests, run:

```bash
pnpm test:unit
```

You can narrow the run down to only files under matching paths:

```bash
pnpm jest --testPathPattern=frontend/src/lib/components/IntervalFilter/intervalFilterLogic.test.ts
```

To update all visual regression test snapshots, make sure Storybook is running on your machine (you can start it with `pnpm storybook` in a separate Terminal tab). You may also need to install Playwright with `pnpm exec playwright install`. And then run:

```bash
pnpm test:visual
```

To only update snapshots for stories under a specific path, run:

```bash
pnpm test:visual:update frontend/src/lib/Example.stories.tsx
```

### Backend

For backend tests, run:

```bash
pytest
```

You can narrow the run down to only files under matching paths:

```bash
pytest posthog/test/test_example.py
```

Or to only test cases with matching function names:

```bash
pytest posthog/test/test_example.py -k test_something
```

To see debug logs (such as ClickHouse queries), add argument `--log-cli-level=DEBUG`.

### End-to-end

For Cypress end-to-end tests, run `bin/e2e-test-runner`. This will spin up a test instance of PostHog and show you the Cypress interface, from which you'll manually choose tests to run. You'll need `uv` installed (the Python package manager), which you can do so with `brew install uv`. Once you're done, terminate the command with Cmd + C.

## Django migrations

To create a new migration, run `DEBUG=1 ./manage.py makemigrations`.

### Non-blocking migrations

Typically a migration generated by Django will not need to be modified. However, if you're adding a new constraint or index, you must tweak the migration so that it doesn't dangerously lock the affected table. We prevent locking by using the `CONCURRENTLY` keyword in Postgres DDL statements. Don't worry about this too much, a check in our CI will flag necessary tweaks as needed!

For an example of how to update a migration to run concurrently, see `posthog/migrations/0415_pluginconfig_match_action.py`

### Resolving merge conflicts

Our database migrations must be applied linearly in order, to avoid any conflicts. With many developers working on the same codebase, this means it's common to run into merge conflicts when introducing a PR with migrations.

To help with this, we have introduced a tool called [django-linear-migrations](https://github.com/adamchainz/django-linear-migrations). When a migration-caused merge conflict arises, you can solve it by running `python manage.py rebase_migration <conflicted Django app> && git add <app>/migrations` (in our case the app is either `posthog` or `ee`).

## Extra: Working with feature flags

When developing locally with environment variable `DEBUG=1` (which enables a setting called `SELF_CAPTURE`),
all analytics inside your local PostHog instance is based on that instance itself – more specifically, the currently selected project.
This means that your activity is immediately reflected in the current project, which is potentially useful for testing features
– for example, which feature flags are currently enabled for your development instance is decided by the project you have open at the very same time.

So, when working with a feature based on feature flag `foo-bar`, [add a feature flag with this key to your local instance](http://localhost:8010/feature_flags/new) and release it there.

If you'd like to have ALL feature flags that exist in PostHog at your disposal right away, run `DEBUG=1 python3 manage.py sync_feature_flags` – they will be added to each project in the instance, fully rolled out by default.

This command automatically turns any feature flag ending in `_EXPERIMENT` as a multivariate flag with `control` and `test` variants.

Backend side flags are only evaluated locally, which requires the `POSTHOG_PERSONAL_API_KEY` env var to be set. Generate the key in [your user settings](http://localhost:8010/settings/user#personal-api-keys).

## Extra: Debugging with VS Code

The PostHog repository includes [VS Code launch options for debugging](https://github.com/PostHog/posthog/blob/master/.vscode/launch.json). Simply go to the `Run and Debug` tab in VS Code, select the desired service you want to debug, and run it. Once it starts up, you can set breakpoints and step through code to see exactly what is happening. There are also debug launch options for frontend and backend tests if you're dealing with a tricky test failure.

> **Note:** You can debug all services using the main "PostHog" launch option. Otherwise, if you are running most of the PostHog services locally with `./bin/start`, for example if you only want to debug the backend, make sure to comment out that service from the [start script temporarily](https://github.com/PostHog/posthog/blob/master/bin/start#L22).

## Extra: Debugging the backend in PyCharm

With PyCharm's built in support for Django, it's fairly easy to setup debugging in the backend. This is especially useful when you want to trace and debug a network request made from the client all the way back to the server. You can set breakpoints and step through code to see exactly what the backend is doing with your request.

### Setup PyCharm

1. Open the repository folder.
2. Setup the python interpreter (Settings… > Project: posthog > Python interpreter > Add interpreter -> Existing):
   - If using manual setup: `path_to_repo/posthog/.venv/bin/python`.
   - If using Flox: `path_to_repo/posthog/.flox/cache/venv/bin/python`.
3. Setup Django support (Settings… > Languages & Frameworks > Django):
   - Django project root: `path_to_repo`
   - Settings: `posthog/settings/__init__py`
4. To run tests correctly in PyCharm, disable the Django test runner:
   - Go to Settings… > Languages & Frameworks > Django
   - Check "Do not use Django test runner"

### Start the debugging environment

1. Instead of manually running `docker compose` you can open the `docker-compose.dev.yml` file and click on the double play icon next to `services`
2. From the run configurations select:
   - "PostHog" and click on debug
   - "Celery" and click on debug (optional)
   - "Frontend" and click on run
   - "Plugin server" and click on run

## Extra: Accessing Postgres

While developing, there are times you may want to connect to the database to query the local database, make changes, etc. To connect to the database, use a tool like pgAdmin and enter these connection details: _host_:`localhost` _port_:`5432` _database_:`posthog`, _username_:`posthog`, _pwd_:`posthog`.

## Extra: Accessing the Django Admin

If you cannot access the Django admin <http://localhost:8000/admin/>, it could be that your local user is not set up as a staff user. You can connect to the database, find your `posthog_user` and set `is_staff` to `true`. This should make the admin page accessible.

## Extra: Sending emails

Emails are configured in `posthog/emails.py`.

To test email functionality during local development, we use Maildev, a lightweight SMTP server with a web interface to inspect sent emails.

Add the following environment variables to your `.env` file:

```.env
EMAIL_HOST=127.0.0.1
EMAIL_PORT=1025
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=false
EMAIL_USE_SSL=false
EMAIL_ENABLED=true
```

With the default `docker-compose.dev.yml` setup, you can view emails in your browser at [http://localhost:1080](http://localhost:1080).

This allows you to easily confirm that emails are being sent and formatted correctly without actually sending anything externally.

Emails sent via SMTP are stored in HTML files in `posthog/templates/*/*.html`. They use Django Template Language (DTL).

## Extra: Use tracing with Jaeger

Jaeger is enabled by default after running `./bin/start`.

Jaeger will be available at [http://localhost:16686](http://localhost:16686).

#### Production usage

We send our PostHog Cloud emails via Customer.io using their HTTP API. If Customer.io is not configured but SMTP is, it will fall back to SMTP. We do this so we can continue to support SMTP emails for self-hosted instances.

#### Setting up Customer.io emails

To start sending via Customer.io, all you need to do is add the `CUSTOMER_IO_API_KEY` variable. Please be careful when using locally, this is only intended for testing emails and should not be used otherwise.

#### Setting up SMTP emails

Most, but not all, emails have been migrated to Customer.io. Some are still sending via SMTP from Django templates. Eventually we will move them all to Customer.io but we will still support SMTP for self-hosted instances.

- Set `EMAIL_HOST`, `EMAIL_PORT`, and `EMAIL_ENABLED` appropriately
- Enable TLS or SSL if required (`EMAIL_USE_TLS=true` or `EMAIL_USE_SSL=true`)
- Provide valid credentials for your email provider using `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`

### Creating a new email

When creating a new email, there are a few steps to take. It's important to add the template to both Customer.io and the `posthog/templates/` folder.

1. Create a new template in Customer.io. Ask @joe or @team-platform for help here if needed
2. Add the new Customer.io template to the `CUSTOMER_IO_TEMPLATE_ID_MAP` in `posthog/email.py`
3. Create a template in PostHog as an SMTP backup. Make sure the file name matches the key used in the template map.
4. Trigger the email with something like this:

    ```python
    message = EmailMessage(
        use_http=True,  # This will attempt to send via Customer.io before falling back to SMTP
        campaign_key=campaign_key,
        subject="This is a subject",
        template_name="test_template",
        template_context={
            ...
        },
    )
    message.add_recipient(email=target_email)
    message.send()
    ```

## Extra: Developing paid features (PostHog employees only)

If you're a PostHog employee, you can get access to paid features on your local instance to make development easier. [Learn how to do so in our internal billing guide](https://github.com/PostHog/billing?tab=readme-ov-file#licensing-your-local-instance).

## Extra: Working with the data warehouse

[See here for working with data warehouse](/handbook/engineering/data-warehouse)
