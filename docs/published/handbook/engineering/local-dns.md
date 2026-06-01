# Local DNS

PostHog's local stack refers to its services by `*.posthog.test` hostnames
(`db.posthog.test`, `clickhouse.posthog.test`, `kafka.posthog.test`, …) in the
shared `.env.services`. One config string resolves everywhere:

- **inside containers** via Docker network aliases (`docker-compose.base.yml`),
- **on your host** via a local DNS resolver — `./bin/setup-local-dns`,
- **in CI** via the `/etc/hosts` lines in the workflows.

This replaces the old hand-maintained `/etc/hosts` line that mapped each bare
Docker service name to `127.0.0.1`.

## Why

Local dev runs the app processes on your host while data services run in
Docker. Inside the Docker network, names resolve via Docker's embedded DNS; on
the host they don't. The previous fix was a static `/etc/hosts` line per
contributor — easy to forget, drifts over time, and can't express wildcards. A
local resolver answers the whole `*.posthog.test` suffix at once.

`.test` is reserved by [RFC 6761](https://www.rfc-editor.org/rfc/rfc6761) for
exactly this — it never resolves publicly and carries none of the HSTS/real-TLD
risk of `.dev`/`.local`.

## Setup

```bash
./bin/setup-local-dns
```

Idempotent. On macOS it installs and configures dnsmasq with
`address=/posthog.test/127.0.0.1` and a `/etc/resolver/posthog.test` entry (no
global DNS change — macOS only routes that suffix to dnsmasq). On Linux it
prints the manual steps; keeping the `/etc/hosts` line there is also fine.

After running it, `clickhouse.posthog.test:9000` resolves to
`127.0.0.1:9000` — the published container port — and `hogli start` works.

> macOS keys `/etc/resolver` on the domain **suffix**, which is why these are
> `*.posthog.test` names and not bare `db`/`kafka`: a resolver can't scope a
> single-label name. That's the same reason `/etc/hosts` was used for them
> before.

## How it composes

- **In-docker / sandbox:** containers reach the services by both the bare
  service name (`clickhouse`) and the suffixed alias
  (`clickhouse.posthog.test`); the aliases live in `docker-compose.base.yml`
  (and the sandbox's inline `db`/`kafka`). Containers never touch your host
  resolver.
- **Kafka:** the broker advertises `internal://kafka.posthog.test:9092`, so
  both host and container clients resolve whatever they reconnect to. The
  external listener stays `localhost:19092`.
- **OrbStack:** orthogonal. dnsmasq owns `*.posthog.test`; OrbStack owns
  `*.orb.local`. Don't also enable OrbStack's "Allow access to container
  domains & IPs" custom-DNS path at the same time — it has a history of
  colliding with user-run resolvers.
- **CI / Linux:** the workflow `/etc/hosts` lines list both the bare and
  suffixed names, so either form resolves.

## Fallback: /etc/hosts

If you'd rather not run a resolver, the suffixed names work in `/etc/hosts` too
(the flox activation hook still offers this line):

```text
127.0.0.1 db.posthog.test redis7.posthog.test kafka.posthog.test clickhouse.posthog.test objectstorage.posthog.test seaweedfs.posthog.test temporal.posthog.test
```
