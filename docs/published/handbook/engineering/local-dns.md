# Local DNS (alternative to editing /etc/hosts)

> **Status: draft / opt-in.** This is an alternative to the manual `/etc/hosts`
> edit described in [developing-locally.md](./developing-locally.md). It is not
> yet the recommended default — it exists so we can try it and discuss.

## Why this exists

Local PostHog dev runs the **app processes on your host** (Django, the
plugin-server, the Rust services) while the **data services run in Docker**
(`db`, `redis7`, `kafka`, `clickhouse`, `objectstorage`, `temporal`, …). One
shared `.env.services` is used both inside containers _and_ by host processes,
and it refers to services by their Docker names (`CLICKHOUSE_HOST=clickhouse`,
`KAFKA_HOSTS=kafka:9092`, …).

Inside the Docker network those names resolve via Docker's embedded DNS. On the
host they don't resolve at all — which is why every contributor has to add a
line to `/etc/hosts`:

```text
127.0.0.1 db redis7 kafka clickhouse clickhouse-coordinator objectstorage seaweedfs temporal
```

That line is static, easy to forget, and can't express wildcards. A local DNS
resolver replaces it with a single rule that covers every current and future
service name.

## How it works

A local [dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html) answers the whole
`*.posthog.test` suffix and points it at loopback:

```ini
address=/posthog.test/127.0.0.1
```

On macOS, `/etc/resolver/posthog.test` tells the system to send only
`*.posthog.test` queries to dnsmasq — no global DNS change. (macOS keys this on
the domain **suffix**, which is why a TLD like `.posthog.test` is required and
bare single-label names such as `db` can't use it — that's the reason
`/etc/hosts` is used for them today.) `.test` is reserved by
[RFC 6761](https://www.rfc-editor.org/rfc/rfc6761) for exactly this, so it never
resolves publicly and carries none of the HSTS/real-TLD risk of `.dev`/`.local`.

The host then resolves e.g. `clickhouse.posthog.test:9000` → `127.0.0.1:9000`,
which is the same published port the `/etc/hosts` mapping reaches today. The
mechanism changes; the target (loopback + published ports) does not.

## Setup

```bash
./bin/setup-local-dns
```

Idempotent. Installs and configures dnsmasq on macOS; prints manual steps on
Linux (where keeping `/etc/hosts` is usually simpler).

## Opt in (host-only, gitignored)

Because precedence in `bin/start` is
`shell env > .env.local > .env.development > .env.services`, you opt in by
overriding the hostnames in your **`.env.local`** (gitignored, host-only —
containers keep the bare names from `.env.services`):

```bash
# .env.local
PGHOST=db.posthog.test
CLICKHOUSE_HOST=clickhouse.posthog.test
REDIS_URL=redis://redis7.posthog.test:6379/
OBJECT_STORAGE_ENDPOINT=http://objectstorage.posthog.test:19000
TEMPORAL_HOST=temporal.posthog.test
```

With this you can drop the PostHog line from `/etc/hosts` entirely (see the
Kafka caveat below).

## How it composes

- **In-docker / sandbox:** unaffected. Containers resolve bare names (`clickhouse`)
  via Docker's embedded DNS and never touch your host's dnsmasq. If we later move
  the suffix into `.env.services` (shared config), each service needs a Docker
  **network alias** (`aliases: [clickhouse.posthog.test]`) so containers resolve
  the suffixed name locally instead of forwarding it upstream.
- **OrbStack:** orthogonal. dnsmasq owns `*.posthog.test`; OrbStack owns
  `*.orb.local`. They don't conflict as long as you keep publishing ports to
  loopback. (Don't also enable OrbStack's "Allow access to container domains &
  IPs" custom-DNS path at the same time — it has a history of colliding with
  user-run resolvers.)
- **CI / Linux:** keep the existing `/etc/hosts` line. This opt-in targets macOS
  dev machines; it doesn't need to change CI.

## Known caveat: Kafka

Kafka clients reconnect to whatever the broker **advertises**, and the dev
broker advertises the bare name `kafka:9092`. So even if the host first dials
`kafka.posthog.test`, the second hop needs bare `kafka` to resolve — which
dnsmasq on `.posthog.test` does not cover. For now, either:

- keep just the `kafka` entry in `/etc/hosts`, or
- point the host at Kafka's **external** listener (`localhost:19092`), which
  needs no DNS.

A full migration would advertise `kafka.posthog.test` instead. Left open for
discussion.

## Open questions for discussion

1. Keep this as an opt-in convenience alongside `/etc/hosts`, or commit to it?
2. If we commit: move the suffix into `.env.services` (shared config) + add
   Docker network aliases + update the ~17 hardcoded host defaults in
   `posthog/settings/`, and resolve the Kafka advertised-listener question.
3. Do we want the flox `on-activate` hook to detect a working resolver and skip
   the `/etc/hosts` nudge when one is present?
