# agent-sandbox-host

Canonical sandbox-host image consumed by **both** sandbox pools in
`@posthog/agent-shared`:

| Pool                | How it uses this image                                                                                                                                                                                                                  |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DockerSandboxPool` | `docker run -v <workdir>:/workdir <image> node /sandbox/host.js`. host.js writes `/workdir/host.alive` so the runner knows the container is ready; dispatches via `docker exec node /sandbox/dispatch.js …`.                            |
| `ModalSandboxPool`  | `client.sandboxes.create(app, image)` with no foreground command — Modal idles by default. Tools + dispatch script are laid out via `sandbox.filesystem.writeText`; dispatches via `sandbox.exec(['node', '/sandbox/dispatch.js', …])`. |

## Layout

- `src/host.js` — long-running process for the Docker pool. Writes
  `/workdir/host.alive` on boot, idles on a heartbeat. **Modal never runs
  this** — its sandbox idles by default.
- `src/dispatch.js` — per-invoke handler. Reads `/workdir/request.json` (or
  whichever path the caller supplies), loads
  `/workdir/tools/<id>/compiled.js`, runs the named action with the supplied
  args + a minimal `ctx`, writes `/workdir/response.json`.
- `src/dispatch.test.js` — node:test unit suite for the dispatcher. Runs
  in-process, no docker required.
- `scripts/smoke-test-image.sh` — **containerized** end-to-end smoke test
  for the built image (see "Smoke test" below).

## Building the image

```bash
cd services/agent-sandbox-host
docker build -t posthog/agent-sandbox-host:dev .
```

In CI the image is published to GHCR as
`ghcr.io/posthog/posthog-agent-sandbox-host:<sha>` and
`ghcr.io/posthog/posthog-agent-sandbox-host:master`. The agent-platform
chart wires the SHA-tagged reference into both pools via the
`SANDBOX_HOST_IMAGE` env var (consumed by `selectSandboxPool()`); production
should always use the SHA tag because Modal caches images by reference
indefinitely.

## Smoke test (containerized)

`scripts/smoke-test-image.sh <image-tag>` builds a self-contained workdir
with a trivial echo tool, mounts it into the image, executes the
dispatcher inside the container, and asserts the response shape. It's the
"this image actually works in isolation" check — runs in CI after the
build and before the push.

```bash
# Build then smoke-test in one shot:
docker build -t posthog/agent-sandbox-host:dev .
./scripts/smoke-test-image.sh posthog/agent-sandbox-host:dev
```

The end-to-end variants (real Modal sandbox / real Docker container with
real tool injection) live in
[`services/agent-shared/src/sandbox/sandbox-modal.test.ts`](../agent-shared/src/sandbox/sandbox-modal.test.ts)
and [`services/agent-shared/src/sandbox/sandbox-docker.test.ts`](../agent-shared/src/sandbox/sandbox-docker.test.ts).
Both are opt-in (Modal needs `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` in env;
Docker needs a local docker daemon).

## Running the unit tests

The dispatcher's pure-function logic (tool loading, action lookup,
timeouts, nonce ref) runs against node:test without the image:

```bash
cd services/agent-sandbox-host
node --test src/dispatch.test.js
```

## Wire format

Request (`/workdir/request.json`):

```json
{
  "toolId": "fetch-acme",
  "action": "default",
  "args": { "name": "world" },
  "timeoutMs": 30000
}
```

Response (`/workdir/response.json`):

```json
{ "ok": true, "result": { "greeted": "world" } }
```

or

```json
{ "ok": false, "error": { "code": "tool_not_found", "message": "..." } }
```

Tool contract (`/workdir/tools/<id>/compiled.js`):

```js
module.exports = {
  id: '<tool-id>',
  actions: {
    default: (args, ctx) => {
      // ctx.secrets.ref('SECRET_NAME')  → nonce string
      // ctx.log('info', 'message', { meta })
      return { ok: true }
    },
  },
}
```

`ctx.secrets.ref(name)` returns the nonce the runner-side `SecretBroker`
minted for this session. The sandbox never sees raw secret values; the
runner substitutes nonces with real values at egress.
