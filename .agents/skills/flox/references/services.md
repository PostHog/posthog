# Flox Services Guide

## Running Services in Flox Environments

- Start with `flox activate --start-services` or `flox activate -s`
- Or set `auto-start = true` under `[services]` so every activation starts them with no flag (see "Auto-Starting Services on Activation" below)
- Run the service in the foreground with `exec` (the default) — Flox manages it; a foreground process needs neither `is-daemon` nor `shutdown.command`
- Only a process that *daemonizes itself* (forks and exits) needs `is-daemon = true`, and it then **requires** a `shutdown.command`
- Use `flox services status/logs/restart` to manage (must be in activated env)
- Service commands don't inherit hook activations; explicitly source/activate what you need

## Core Commands

```bash
flox activate -s                # Start services
flox services status            # Check service status
flox services logs <service>    # View service logs
flox services restart <service> # Restart a service
flox services stop <service>    # Stop a service
```

## Auto-Starting Services on Activation

By default services only run when asked for: `flox activate -s` /
`flox activate --start-services`, or `flox services start` from inside
an activation. To make them start on *every* activation with no flag,
set `auto-start = true` in the `[services]` table:

```toml
schema-version = "1.12.0"

[services]
auto-start = true

[services.web]
command = '''exec python -m http.server "$WEB_PORT"'''

[vars]
WEB_PORT = "8000"
```

The details that are easy to get wrong:

- **`auto-start` belongs to the `[services]` table itself, not to a
  service.** It is a sibling of the service names and applies to *all*
  of them — there is no per-service form. Put it directly under the
  `[services]` header, before the first `[services.<name>]` block.
  Placing it inside a service is a parse error: ``unknown field
  `auto-start`, expected one of `command`, `vars`, `is-daemon`,
  `shutdown`, `systemd`, `systems` ``.
- **It requires `schema-version = "1.12.0"` or newer** (the schema
  version that introduced it). In a `version = 1` manifest the same key
  fails to parse: ``invalid type: boolean `true`, expected struct
  ServiceDescriptor in `services.auto-start` ``. Replace the
  `version = 1` line with `schema-version = "1.12.0"` in the same edit
  (leave an already-higher `schema-version` alone). The two keys are
  mutually exclusive — a manifest carrying both is rejected.
  This is one instance of a general rule, covered in full in
  `references/schema-versions.md`, and worth knowing before you edit any
  manifest:
  - A `schema-version` value **is a minimum flox CLI version.** Setting
    `"1.12.0"` says "flox 1.12.0 or newer required"; an older CLI stops
    with `manifest had invalid schema version '1.12.0'`. So bumping the
    schema to reach `auto-start` also raises the floor for everyone
    sharing the environment — mention that when the env is pushed to
    FloxHub or shared with a team.
  - **Only releases that changed the schema have a version.** The list
    is `version = 1` (up to flox 1.9.1, before `schema-version`
    existed), then `"1.10.0"`, `"1.11.0"`, `"1.12.0"`, `"1.13.0"`,
    `"1.14.0"` — not every flox release.
  - **New environments start at the CLI's newest schema.** `flox init`
    has written a `schema-version` since flox 1.10.0, and on 1.13.2 it
    writes `"1.13.0"`. So an environment created by a recent flox is
    often already new enough for `auto-start` — read the first line
    before you change it. That is because of how it was *created*, not
    because something upgraded it later.
  - **Flox forward-migrates only when an operation needs it.** It
    rewrites the version line when the result of a command no longer
    fits the schema the file declares (`flox install openssl` on a
    `version = 1` manifest jumps to `"1.13.0"`, because recording a
    multi-output package needs `outputs`), and leaves it alone when
    nothing requires the change (`flox install hello`). It is the
    environment's contents that decide this, not which command you ran —
    even a plain `flox activate` can bump the line. Don't count on it
    having happened either way; read the first line.
  - **Migration will never save your edit.** Flox parses before it
    migrates, so adding `auto-start` while the file still says
    `version = 1` is rejected outright — the migration logic never sees
    it. Bump the version line in the *same* edit that adds the key.
- **The default is off.** Omitting the key behaves exactly like
  `auto-start = false`: activation starts nothing.
- **Per-activation overrides still win.** `flox activate
  --no-start-services` suppresses auto-start for that activation, and
  `flox activate -s` starts services even when `auto-start` is unset.
- **Auto-activation respects it too.** Directory auto-activation
  (`flox activate allow`) does not start services unless the manifest
  sets `auto-start = true`.
- **Composed environments:** the including manifest's `auto-start` wins;
  if it doesn't set one, the value from the included environment is
  inherited.

To turn it back off, set `auto-start = false` or delete the key — both
mean "don't start on activate"; keep the explicit `false` when the
intent is worth recording in the manifest.

## Network Services Pattern

Always make host/port configurable via vars:

```toml
[services.webapp]
command = '''exec app --host "$APP_HOST" --port "$APP_PORT"'''

[vars]
APP_HOST = "0.0.0.0"  # Network-accessible
APP_PORT = "8080"
```

## Service Logging Pattern

Always pipe to `$FLOX_ENV_CACHE/logs/` for debugging:

```toml
[services.myapp]
command = '''
  mkdir -p "$FLOX_ENV_CACHE/logs"
  exec app 2>&1 | tee -a "$FLOX_ENV_CACHE/logs/app.log"
'''
```

## Python venv Pattern for Services

Services must activate venv independently:

```toml
[services.myapp]
command = '''
  [ -f "$FLOX_ENV_CACHE/venv/bin/activate" ] && \
    source "$FLOX_ENV_CACHE/venv/bin/activate"
  exec python-app "$@"
'''
```

Or use venv Python directly:

```toml
[services.myapp]
command = '''exec "$FLOX_ENV_CACHE/venv/bin/python" app.py'''
```

## Using Packaged Services

Override package's service by redefining with same name.

## Database Service Examples

### Choosing TCP vs. Unix socket

Flox-managed datastores can bind a TCP port, a Unix domain socket, or
both. The right default depends on how the *client* connects, not habit:

- **Unix socket** avoids colliding with a developer's own instance of
  the same datastore already listening on its default port (a second
  Postgres on 5432, a second Redis on 6379). It's transparent for
  env-var-driven clients that already resolve a socket path (libpq's
  `PGHOST`, and anything built on it — `psql`, `psycopg2`, the `pg`
  gem). Point it at a short, project-named path, e.g.
  `/tmp/<project>-postgres` — `$FLOX_ENV_CACHE` is usually too long for
  a Unix socket path (the `AF_UNIX` path limit is 108 bytes on Linux,
  104 on macOS), and a bare `/tmp` default collides with every other
  floxified project on the machine once the socket filename is derived
  from the port.
- **TCP** is required for clients that parse a URL-shaped connection
  string themselves instead of deferring to the driver's socket
  convention (Prisma and similar ORMs reading `DATABASE_URL`/
  `REDIS_URL` directly), and for anything that can't speak Unix sockets
  at all.

Not every datastore below can go socket-only — check each one's note
before dropping TCP.

### PostgreSQL

**Unix socket (default)** — socket-only; `-k` plus
`listen_addresses=''` disables TCP entirely, so this only serves
clients that resolve `PGHOST` to a socket directory (any libpq-based
driver). Pass `-c listen_addresses=''` at both `initdb`/bootstrap time
and in the steady-state `[services.postgres]` command — a fresh
cluster still attempts a TCP bind during its own bootstrap start
otherwise, and that bind fails silently if a host Postgres already
holds 5432.

```toml
[install]
postgresql_16.pkg-path = "postgresql_16"

[vars]
PGHOST = "/tmp/myapp-postgres"
PGPORT = "5432"
PGUSER = "postgres"
PGDATABASE = "myapp_dev"

[hook]
on-activate = '''
  mkdir -p "$PGHOST"
  if [ ! -d "$FLOX_ENV_CACHE/postgres" ]; then
    initdb -D "$FLOX_ENV_CACHE/postgres" \
      --username="$PGUSER" \
      --auth=trust \
      --no-locale \
      --encoding=UTF8 >&2
    pg_ctl -D "$FLOX_ENV_CACHE/postgres" \
      -o "-p $PGPORT -k $PGHOST -c listen_addresses=''" \
      -l "$FLOX_ENV_CACHE/postgres/init.log" start
    until pg_isready -h "$PGHOST" -p "$PGPORT" -q; do sleep 0.2; done
    createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDATABASE"
    pg_ctl -D "$FLOX_ENV_CACHE/postgres" stop -m fast
  fi
'''

[services.postgres]
command = '''
  exec postgres \
    -D "$FLOX_ENV_CACHE/postgres" \
    -p "$PGPORT" \
    -k "$PGHOST" \
    -c listen_addresses=""
'''
```

`auth=trust` is dev-only — call it out if this manifest leaves your
machine.

**TCP** — for a client that parses `DATABASE_URL` itself instead of
resolving `PGHOST` (Prisma and similar ORMs), or when nothing else in
the environment needs the socket. Same `PGHOST`/`PGPORT` vars as the
socket form above — libpq inspects the value and treats a leading `/`
as a socket directory, anything else as a hostname, so a plain
hostname here is what makes this the TCP form. If something else
still expects the socket (`psql` invoked without `-h`), set `PGHOST`
back to a directory and add `-k "$PGHOST"` alongside the TCP bind
instead of dropping it — TCP is additive here, not a replacement.

```toml
[services.postgres]
command = '''
  mkdir -p "$FLOX_ENV_CACHE/postgres"
  if [ ! -d "$FLOX_ENV_CACHE/postgres/data" ]; then
    initdb -D "$FLOX_ENV_CACHE/postgres/data"
  fi
  exec postgres -D "$FLOX_ENV_CACHE/postgres/data" \
    -h "$PGHOST" \
    -p "$PGPORT"
'''

[vars]
PGHOST = "127.0.0.1"
PGPORT = "5432"
PGUSER = "myuser"
PGDATABASE = "mydb"
```

### Redis

Redis has no equivalent of libpq's `PGHOST` auto-detection — no
standard Redis client reads a socket-path env var, and an app with
`REDIS_URL` unset still falls back to `redis://127.0.0.1:6379`.
**Never run Redis socket-only**; the choice is TCP alone, or TCP with
a socket wired alongside for the app that can use one.

**TCP** — the simple default when nothing on the box needs a socket:

```toml
[services.redis]
command = '''
  mkdir -p "$FLOX_ENV_CACHE/redis"
  exec redis-server \
    --bind "$REDIS_HOST" \
    --port "$REDIS_PORT" \
    --dir "$FLOX_ENV_CACHE/redis"
'''

[vars]
REDIS_HOST = "127.0.0.1"
REDIS_PORT = "6379"
```

**TCP + Unix socket** — add `--unixsocket` alongside the TCP bind, not
in place of it, for the client that can use one. Name the socket file
after the project (`myapp-redis.sock`, not a bare `redis.sock`) so it
doesn't collide with another floxified project's socket in `/tmp`.

```toml
[install]
redis.pkg-path = "redis"

[vars]
REDIS_URL = "redis://localhost:6379"

[hook]
on-activate = '''
  mkdir -p "$FLOX_ENV_CACHE/redis"
'''

[services.redis]
command = '''
  exec redis-server \
    --port 6379 \
    --unixsocket /tmp/myapp-redis.sock \
    --dir "$FLOX_ENV_CACHE/redis" \
    --save "" \
    --appendonly no
'''
```

`--save ""` and `--appendonly no` disable persistence — fine for dev,
but data resets on every service stop; drop them if you need
durability across restarts.

### MongoDB

MongoDB doesn't support a socket-only listener the way Postgres
does — `mongod` always binds a TCP port and can *additionally* expose
a Unix socket, the same TCP + socket shape as Redis above.

**TCP** — the simple default:

```toml
[services.mongodb]
command = '''
  mkdir -p "$FLOX_ENV_CACHE/mongodb"
  exec mongod \
    --dbpath "$FLOX_ENV_CACHE/mongodb" \
    --bind_ip "$MONGODB_HOST" \
    --port "$MONGODB_PORT" \
    --nounixsocket
'''

[vars]
MONGODB_HOST = "127.0.0.1"
MONGODB_PORT = "27017"
```

**TCP + Unix socket** — `mongod` opens a socket automatically unless
`--nounixsocket` is passed, but its default directory is a bare
`/tmp` — scope it to the project with `--unixSocketPrefix`, the same
way the Postgres and Redis patterns above scope their socket paths.
The prefix below yields a socket file at
`/tmp/myapp-mongodb/mongodb-27017.sock` — the filename is always
`mongodb-<port>.sock`, the same "name it after the project" discipline
as the Redis `.sock` file above.

```toml
[services.mongodb]
command = '''
  mkdir -p "$FLOX_ENV_CACHE/mongodb" /tmp/myapp-mongodb
  exec mongod \
    --dbpath "$FLOX_ENV_CACHE/mongodb" \
    --bind_ip "$MONGODB_HOST" \
    --port "$MONGODB_PORT" \
    --unixSocketPrefix /tmp/myapp-mongodb
'''

[vars]
MONGODB_HOST = "127.0.0.1"
MONGODB_PORT = "27017"
```

Mongo drivers are URL-driven by convention (`mongodb://` connection
strings), unlike libpq's `PGHOST` auto-detection — so consuming the
socket here is the deliberate, advanced case: percent-encode the
socket path into the URI's host segment:

```
mongodb://%2Ftmp%2Fmyapp-mongodb%2Fmongodb-27017.sock
```

## Web Server Examples

### Node.js Development Server

```toml
[services.dev-server]
command = '''
  exec npm run dev -- --host "$DEV_HOST" --port "$DEV_PORT"
'''

[vars]
DEV_HOST = "0.0.0.0"
DEV_PORT = "3000"
```

### Python Flask/FastAPI

```toml
[services.api]
command = '''
  source "$FLOX_ENV_CACHE/venv/bin/activate"
  exec python -m uvicorn main:app \
    --host "$API_HOST" \
    --port "$API_PORT" \
    --reload
'''

[vars]
API_HOST = "0.0.0.0"
API_PORT = "8000"
```

### Simple HTTP Server

```toml
[services.web]
command = '''exec python -m http.server "$WEB_PORT"'''

[vars]
WEB_PORT = "8000"
```

## Environment Variable Convention

Use variables like `REDIS_HOST`, `REDIS_PORT` to define where services run.

These store connection details *separately*:
- `*_HOST` is the hostname or IP address (e.g., `localhost`, `db.example.com`)
- `*_PORT` is the network port number (e.g., `5432`, `6379`)

Postgres is the one exception: it uses libpq's own `PGHOST`/`PGPORT`
names instead of the generic `POSTGRES_HOST`/`POSTGRES_PORT` shape, and
`PGHOST` can hold either a hostname (TCP form) or a socket
**directory** (socket form) — libpq inspects the value and picks the
transport automatically. See PostgreSQL above for both forms.

This pattern ensures users can override them at runtime:
```bash
REDIS_HOST=cache.internal REDIS_PORT=6380 flox activate -s
```

Use consistent naming across services so the meaning is clear to any system or person reading the variables.

## Service with Shutdown Command

```toml
[services.myapp]
# `myapp start` forks a background daemon and returns — that's why this needs
# is-daemon + a shutdown command (a foreground `exec` service needs neither).
command = '''myapp start'''
is-daemon = true

[services.myapp.shutdown]
command = '''myapp stop'''
```

## Dependent Services

Services can wait for other services to be ready. This example uses
the Unix-socket Postgres form above (`$PGHOST` is a directory); set
`PGHOST` to a hostname instead (and drop `-k`) if this environment uses
the TCP form instead — see PostgreSQL above.

```toml
[services.db]
command = '''
  exec postgres -D "$FLOX_ENV_CACHE/postgres" \
    -p "$PGPORT" \
    -k "$PGHOST" \
    -c listen_addresses=""
'''

[services.api]
command = '''
  # Wait for database
  until pg_isready -h "$PGHOST" -p "$PGPORT"; do
    sleep 1
  done
  exec python -m uvicorn main:app
'''

[vars]
PGHOST = "/tmp/myapp-postgres"
PGPORT = "5432"
```

## Service Health Checks

```toml
[services.api]
command = '''
  # Health check function
  health_check() {
    curl -sf http://localhost:8000/health > /dev/null
  }

  exec python -m uvicorn main:app --host 0.0.0.0 --port 8000
'''
```

## Best Practices

- Log service output to `$FLOX_ENV_CACHE/logs/`
- Test activation with `flox activate -- <command>` before adding to services
- When debugging services, run the exact command from manifest manually first
- Always make host/port configurable via vars for network services
- Use `exec` to replace the shell process with the service command
- Services must activate venv inside service command, not rely on hook activation
- Run services in the foreground with `exec` (the default); only set `is-daemon = true` — which then requires a `shutdown.command` — for a command that daemonizes itself

## Debugging Service Issues

### Check Service Status
```bash
flox services status
```

### View Service Logs
```bash
flox services logs myservice
```

### Run Service Command Manually
```bash
flox activate
# Copy the exact command from manifest and run it
```

### Check if Service is Listening

TCP:
```bash
# Check if port is open
lsof -i :8000
netstat -an | grep 8000

# Test connection
curl http://localhost:8000
nc -zv localhost 8000
```

Unix socket — the port-based checks above don't apply; check the
socket file itself:
```bash
# Confirm the socket file exists
test -S /tmp/myapp-postgres/.s.PGSQL.5432 && echo "socket present"

# See what's listening on it
lsof -U | grep myapp-postgres
ss -x | grep myapp-postgres

# Test connection (Postgres example — PGHOST as a directory)
psql -h /tmp/myapp-postgres -p 5432 -U postgres -c 'select 1'
```

## Common Pitfalls

### Services Don't Preserve State
Services see fresh environment (no preserved state between restarts). Store persistent data in `$FLOX_ENV_CACHE`.

### Service Commands Don't Inherit Hook Activations
Explicitly source/activate what you need inside the service command.

### Forgetting to Create Directories
Always `mkdir -p` for data directories in service commands.

### Port Conflicts
Use configurable ports via variables to avoid conflicts with other
services. For datastores specifically, prefer a Unix socket (see
Database Service Examples) — it sidesteps the conflict entirely instead
of just making it configurable.

