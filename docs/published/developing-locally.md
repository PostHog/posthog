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
- Node.js services (handles event ingestion and apps/plugins)
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

When spinning up an instance of PostHog for development, we recommend the following hybrid configuration:

- External services (ClickHouse, Kafka, PostgreSQL, Redis, etc.) run in Docker via `docker compose`
- PostHog apps (Django, frontend, plugin-server, Celery) run on the host using `hogli start` (which uses mprocs, a terminal UI, to manage and display logs from all processes simultaneously)

This approach gives you fast iteration on the code you're developing while keeping infrastructure isolated.

> It is also technically possible to run PostHog in Docker completely, but syncing code changes is then much slower, and for development you need PostHog dependencies installed on the host anyway (such as formatting or typechecking tools).
> The other way around – everything on the host, is not practical due to significant complexities involved in instantiating Kafka or ClickHouse from scratch.

The instructions here assume you're running macOS or the current Ubuntu Linux LTS (24.04).

For other Linux distros, adjust the steps as needed (e.g. use `dnf` or `pacman` in place of `apt`).

Windows isn't supported natively. But, Windows users can run a Linux virtual machine. The latest Ubuntu LTS Desktop is recommended. (Ubuntu Server is not recommended as debugging the frontend will require a browser that can access localhost.)

In case some steps here have fallen out of date, please tell us about it – feel free to [submit a patch](https://github.com/PostHog/posthog.com/blob/master/contents/handbook/engineering/developing-locally.md)!

## Option 1: Developing locally

This is the recommended option for most developers.

### Prerequisites

#### macOS

1. Install Xcode Command Line Tools if you haven't already: `xcode-select --install`.

2. Install the package manager Homebrew by following the [Homebrew installation instructions](https://brew.sh/).

<blockquote class="warning-note">
    After installation, make sure to follow the instructions printed in your terminal to add Homebrew to your{' '}
    <code>$PATH</code>. Otherwise the command line will not know about packages installed with <code>brew</code>.
</blockquote>

3. Install [OrbStack](https://orbstack.dev/) – a more performant Docker Desktop alternative – with `brew install orbstack`. Go to OrbStack settings and set the memory usage limit to **at least 4 GB** (or 8 GB if you can afford it) + the CPU usage limit to at least 4 cores (i.e. 400%). You'll want to use Brex for the license if you work at PostHog.

4. Continue with [cloning the repository](#cloning-the-repository).

#### Ubuntu

> Note: Importantly, if you're internal to PostHog we are standardised on working on MacOS (not Linux). In part because of SOC2 auditing gains it gives us.

1. Install Docker following the [official Docker installation guide for Ubuntu](https://docs.docker.com/engine/install/ubuntu/).

2. Install the `build-essential` package:

   ```bash
   sudo apt install -y build-essential
   ```

3. Continue with [cloning the repository](#cloning-the-repository).

#### Cloning the repository

Clone the [PostHog repo](https://github.com/posthog/posthog). All future commands assume you're inside the `posthog/` folder.

```bash
git clone --filter=blob:none https://github.com/PostHog/posthog && cd posthog/
```

**Performance tip:** The `--filter=blob:none` flag downloads all commit history and tree structure, but defers file contents (blobs) until needed. This reduces the clone from ~3 GB to a few hundred MB and makes the initial clone **15-17x faster**. You still get full git history for commands like `git log` and `git diff` – blobs are fetched on demand as you use them.

> The `feature-flags` container relies on the presence of the GeoLite cities
> database in the `/share` directory. If you haven't run `./bin/start` this database may not exist.
> You can explicitly download it by running `./bin/download-mmdb`. You may also need to modify the
> file permissions of the database with:
>
> `chmod 0755 ./share/GeoLite2-City.mmdb`

### Setup with Flox (recommended)

Set up your development environment instantly using [Flox](https://flox.dev/).

Flox manages your development environment. The `manifest.toml` file declares all dependencies (similar to `package.json`), and Flox automatically provides the correct versions for your system.

To get PostHog running in a dev environment:

1. Once you have cloned the repo and installed OrbStack, install Flox:

   ```bash
   brew install flox
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

If you need to set up without Flox, see the [manual development setup](/handbook/engineering/manual-dev-setup) guide.

### Common gotchas

These issues can occur regardless of whether you're using Flox or manual setup.

**Docker/OrbStack resource limits**
If you see "Exit Code 137" or out-of-memory errors, your Docker container doesn't have enough resources. In OrbStack settings, allocate **at least 4 GB RAM** (8 GB recommended) and **at least 4 CPU cores** (400%).

**Docker not running**
If you see `Error while fetching server API version: 500 Server Error for http+docker://localhost/version`, make sure Docker (or OrbStack) is actually running.

**Port conflicts**
If you see a port binding error for 5432, you have Postgres running locally. Use `lsof -i :5432` to find the process, then `sudo service postgresql stop` to stop it.

**GeoLite database missing**
The feature-flags container needs the GeoLite database in `/share`. If it's missing, run `./bin/download-mmdb` and then `chmod 0755 ./share/GeoLite2-City.mmdb`.

**ClickHouse "get_mempolicy" warning**
You might see `get_mempolicy: Operation not permitted` in the ClickHouse logs. This is harmless and can be ignored. To verify ClickHouse started properly, run `docker exec -it posthog-clickhouse-1 bash` then `clickhouse-client --query "SELECT 1"`.

**Database migration errors**
If you see `fe_sendauth: no password supplied`, set `DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog` and ensure containers are running. On ARM machines, you may also hit `psycopg2` errors – see [this comment](https://github.com/psycopg/psycopg2/issues/1216#issuecomment-820556849) for fixes.

**Frontend typegen stuck in loop**
The first time you run typegen, it may get stuck. Cancel it (`Ctrl+C`), run `git reset --hard`, then try again. You may need to discard changes once more when the second round completes.

**"layout.html is not defined" error**
This happens on first startup. Wait for the frontend to finish compiling and try accessing the app again.

**Kafka segfaults on ARM**
Kafka is an x86 container and may segfault randomly on ARM machines. Simply restart it when that happens.

**Apple Silicon OpenSSL issues**
On Apple Silicon Macs, you may get build errors related to OpenSSL. For nodejs: set `CPPFLAGS=-I/opt/homebrew/opt/openssl/include` and `LDFLAGS=-L/opt/homebrew/opt/openssl/lib` before installing. For Python packages, you may need custom OpenSSL headers – consult the [xmlsec issue](https://github.com/xmlsec/python-xmlsec/issues/254) for details.

**Nodejs services rebuild**
If the nodejs won't start, try `cd nodejs && pnpm rebuild && pnpm i`.

**Python setuptools error**
If you see `import gyp  # noqa: E402` during nodejs install, run `brew install python-setuptools`.

**OpenSSL certificate verification error**
If you get `Configuration property "enable.ssl.certificate.verification" not supported in this build: OpenSSL not available at build time` when running `./bin/start`, set the right OpenSSL environment variables as described in [this issue](https://github.com/xmlsec/python-xmlsec/issues/261#issuecomment-1630889826) and try again.

**pyproject.toml parse warnings**
When running `uv sync`, you may see a `Failed to parse` warning related to `pyproject.toml`. This is usually harmless – if you see the `Activate with:` line at the end, your environment was created successfully.

## Option 2: Developing with Codespaces

This is a faster option to get up and running if you can't or don't want to set up locally.

1. Create your codespace.
   ![](https://user-images.githubusercontent.com/890921/231489405-cb2010b4-d9e3-4837-bfdf-b2d4ef5c5d0b.png)
2. Update it to 8-core machine type (the smallest is probably too small to get PostHog running properly).
   ![](https://user-images.githubusercontent.com/890921/231490278-140f814e-e77b-46d5-9a4f-31c1b1d6956a.png)
3. Open the codespace, using one of the "Open in" options from the list.
4. In the codespace, open a terminal window and run `docker compose -f docker-compose.dev.yml up`.
5. Ensure that you are using the right Node version (`nvm install 22 && nvm use 22`) then, in another terminal, run `pnpm i` (and use the same terminal for the following commands).
6. Then run `uv sync`
   - If this doesn't activate your python virtual environment, run `uv venv` (install `uv` following the [uv standalone installer guide](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer) if needed)
7. Install `sqlx-cli` with `cargo install sqlx-cli` (install Cargo following the [Cargo getting started guide](https://doc.rust-lang.org/cargo/getting-started/installation.html) if needed)
8. Now run `DEBUG=1 ./bin/migrate`
9. Install [mprocs](https://github.com/pvolok/mprocs#installation) (`cargo install mprocs`)
10. Run `./bin/start`.
11. Open browser to <http://localhost:8010/>.
12. To get some practical test data into your brand-new instance of PostHog, run `DEBUG=1 ./manage.py generate_demo_data`.

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

For detailed guidance on non-blocking migrations, see the [Safe Django Migrations](./safe-django-migrations) guide.

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
   - "Nodejs services" and click on run

## Extra: Accessing Postgres

While developing, there are times you may want to connect to the database to query the local database, make changes, etc. To connect to the database, use a tool like pgAdmin and enter these connection details: _host_:`localhost` _port_:`5432` _database_:`posthog`, _username_:`posthog`, _pwd_:`posthog`.

## Extra: Accessing ClickHouse

To connect to ClickHouse using a tool like DataGrip or PyCharm, use these connection details: _host_:`localhost` _port_:`8123` _database_:`default`, _username_:`app`, _pwd_:`apppass`.

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

## Extra: Integrating with slack

You can connect to a real slack workspace in your local development setup by adding the required slack environment variables to your `.env` file.

If you're a PostHog employee, you can find the environment variables in 1Password under `Slack config local dev`.

```.env
SLACK_APP_CLIENT_ID=
SLACK_APP_CLIENT_SECRET=
SLACK_APP_SIGNING_SECRET=
```

When creating the slack integration it will redirect you to `https://localhost...` to hit the webhook, and you may need to manually adjust that to `http://localhost...` if you don't have local https set up.

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

## Extra: Resetting your local database

If you need to start fresh with a clean database (for example, if your local data is corrupted or you want to test the initial setup), follow these steps:

1. Stop all PostHog services and remove all Docker volumes:

   ```bash
   hogli dev:reset
   ```

   This will remove all data stored in Docker volumes, including your PostgreSQL, ClickHouse, and Redis data.

2. Start PostHog again:

   ```bash
   hogli start
   ```

3. Wait for all migrations to complete. You can monitor the logs to ensure migrations have finished running.

4. Once PostHog is running, click the **generate-demo-data** button in the UI, then type `r` to generate test data.

> **Note:** This process will completely wipe your local database. Make sure you don't have any important local data before proceeding.

## Extra: Working with the data warehouse

[See here for working with data warehouse](/handbook/engineering/data-warehouse)
