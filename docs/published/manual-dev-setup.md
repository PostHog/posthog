---
title: Manual development setup
sidebar: Docs
showTitle: true
---

# Manual setup

This documentation is deprecated, and likely not up to date. Please use the [Flox-based instant setup](/handbook/engineering/developing-locally#setup-with-flox-recommended) instead.

## 1. Spin up external services

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

> **Friendly tip 4:** If you see `Error: (HTTP code 500) server error - Ports are not available: exposing port TCP 0.0.0.0:5432 -> 0.0.0.0:0: listen tcp 0.0.0.0:5432: bind: address already in use`, you have Postgres already running somewhere. Try `docker compose -f docker-compose.dev.yml` first, alternatively run `lsof -i :5432` to see what process is using this port.

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
> ```

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

## 2. Prepare the frontend

1. Install nvm, with `brew install nvm` or by following the instructions at <https://github.com/nvm-sh/nvm>. If using fish, you may instead prefer <https://github.com/jorgebucaran/nvm.fish>.

<blockquote class="warning-note">
    After installation, make sure to follow the instructions printed in your terminal to add NVM to your{' '}
    <code>$PATH</code>. Otherwise the command line will use your system Node.js version instead.
</blockquote>

2. Install the latest Node.js 22 (the version used by PostHog in production) with `nvm install 22`. You can start using it in the current shell with `nvm use 22`.

3. Install pnpm by running `corepack enable` and then running `corepack prepare pnpm@10 --activate`. Validate the installation with `pnpm --version`.

4. Install Node packages by running `pnpm i`.

5. Run `pnpm --filter=@posthog/frontend typegen:write` to generate types for [Kea](https://keajs.org/) state management logics used all over the frontend.

> The first time you run typegen, it may get stuck in a loop. If so, cancel the process (`Ctrl+C`), discard all changes in the working directory (`git reset --hard`), and run `pnpm typegen:write` again. You may need to discard all changes once more when the second round of type generation completes.

## 3. Prepare nodejs services

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

2. Run `pnpm --filter=@posthog/nodejs install` to install all required packages. We'll actually run the nodejs services in a later step.

> **Note:** If you face an error like `ld: symbol(s) not found for architecture arm64`, most probably your openssl build flags are coming from the wrong place. To fix this, run:

```bash
export CPPFLAGS=-I/opt/homebrew/opt/openssl/include
export LDFLAGS=-L/opt/homebrew/opt/openssl/lib
pnpm --filter=@posthog/nodejs install
```

> **Note:** If you face an error like `import gyp  # noqa: E402`, most probably need to install `python-setuptools`. To fix this, run:

```bash
brew install python-setuptools
```

> **Troubleshooting nodejs services issues:** If you encounter problems starting up the nodejs services, try these debugging steps:

```bash
cd nodejs
pnpm rebuild
pnpm i
```

## 4. Prepare the Django server

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

1. Install Python 3.12.
   - On macOS, you can do so with Homebrew: `brew install python@3.12`.

   - On Debian-based Linux:

     ```bash
     sudo add-apt-repository ppa:deadsnakes/ppa -y
     sudo apt update
     sudo apt install python3.12 python3.12-venv python3.12-dev -y
     ```

Make sure when outside the venv to always use `python3` instead of `python`, as the latter may point to Python 2.x on some systems. If installing multiple versions of Python 3, such as by using the `deadsnakes` PPA, use `python3.12` instead of `python3`.

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
   CFLAGS="-I /opt/homebrew/opt/openssl/include $(python3.12-config --includes)" LDFLAGS="-L /opt/homebrew/opt/openssl/lib" GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1 GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1 uv sync
   ```

   > **Friendly tip:** If you see `ERROR: Could not build wheels for xmlsec`, refer to this [issue](https://github.com/xmlsec/python-xmlsec/issues/254).

   These will be used when installing `grpcio` and `psycopg2`. After doing this once, and assuming nothing changed with these two packages, next time simply run:

   ```bash
   uv sync
   ```

## 5. Prepare databases

We now have the backend ready, and Postgres and ClickHouse running – these databases are blank slates at the moment however, so we need to run _migrations_ to e.g. create all the tables:

```bash
cargo install sqlx-cli # If you haven't already
DEBUG=1 ./bin/migrate
```

> **Friendly tip 1:** The error `fe_sendauth: no password supplied` connecting to Postgres happens when the database is set up with a password and the user:pass isn't specified in `DATABASE_URL`. Try `export DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog`.

> **Friendly tip 2:** You may run into `psycopg2` errors while migrating on an ARM machine. Try out the steps in this [comment](https://github.com/psycopg/psycopg2/issues/1216#issuecomment-820556849) to resolve this.

> **Friendly tip 3:** When migrating, make sure the containers are running (detached or in a separate terminal tab).

## 6. Start PostHog

Now start all of PostHog (backend, worker, nodejs services, and frontend – simultaneously) with one of:

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

## 7. Develop

This is it – you should be seeing the PostHog app at <a href="http://localhost:8010" target="_blank">http://localhost:8010</a>.

You can now change PostHog in any way you want. See [Project structure](/handbook/engineering/project-structure) for an intro to the repository's contents. To commit changes, create a new branch based on `master` for your intended change, and develop away.
