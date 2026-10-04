# CDP and proxy liveness

Only CDP has an implementation and tests in this change. No workload enables it automatically.
Chart wiring is a separate follow-up. Do not apply these paths to other images.

## Image and application check

CDP runs from `Dockerfile.node`. Its final stage uses `node:24.13.0-bookworm-slim` and the `posthog` user (UID 10001).
The default command is `node nodejs/dist/index.js`.
The image contains these files:

| Path                                      | Purpose                    | Mode       |
| ----------------------------------------- | -------------------------- | ---------- |
| `/usr/local/bin/node`                     | Existing Node.js runtime   | Executable |
| `/code/nodejs/bin/check-cdp-liveness.mjs` | CDP exec entrypoint        | 0755       |
| `/code/nodejs/bin/check-proxy.mjs`        | Separate local proxy check | 0644       |
| `/code/nodejs/bin/liveness-http.mjs`      | Bounded local HTTP request | 0644       |

The entrypoint uses the Node.js standard library. It does not need a shell, package installation, or child processes.
Its absolute shebang does not need `PATH`.

The application check calls `http://127.0.0.1:6738/_health`.
`HTTP_SERVER_PORT` overrides the port, as it does for CDP. It must contain an integer from 1 through 65535.
The existing handler in `nodejs/src/common/api/router.ts` runs the registered service checks.
It returns HTTP 200 when all checks pass and HTTP 503 when a check fails.
The probe keeps that decision. It does not substitute a socket check, process check, or readiness check.
Like the existing Kubernetes HTTP probe, it does not parse the application response body.
It rejects redirects and other status codes; the CDP health handler does not return them.

## Contract

- Without arguments, run only the application check.
- With `--proxy-sidecar`, require the application check and both local proxy checks.
- Check the TCP listener at `127.0.0.1:4750`.
- Request `http://127.0.0.1:9810/metrics` directly. Do not follow redirects.
- Require HTTP 200 and a complete `text/plain` response, at most 1 MiB.
- Require a `go_goroutines` sample with a nonnegative integer value from the proxy's Go Prometheus registry.
- This sample rejects empty or unrelated responses. It is not a complete Prometheus parser or a forwarding test.
- Run all required checks concurrently. Each operation has a 2,000 ms deadline, including body transfer.
- Close each socket at completion or timeout. Do not retry within a probe.
- Exit 0 only when all required checks pass. Exit 1 on failure or invalid input.
- Print only fixed failure messages to stderr. Do not print response bodies, environment values, or credentials.
- Name the failed component. The proxy listener and the proxy metrics endpoint print separate fixed messages.

The production endpoints and deadlines are fixed, except for `HTTP_SERVER_PORT`.
The module parameters used by tests are not operator settings.
The check never reads or changes `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, or their lowercase forms.
It does not infer sidecar mode from proxy variables. It does not use DNS or an external destination.

Use a Kubernetes `timeoutSeconds` of at least 5.
The two-second operation deadline leaves time for process startup and scheduling.
CPU starvation can consume that margin. Kubernetes remains the outer execution deadline.
Keep the existing startup delay, period, and failure threshold unless a dev test supports a change.

Later Rust and Django/Python implementations can use this same opt-in argument, local endpoints, deadlines, and exit rules.
Each implementation must preserve its own application health check.
Use that image's runtime and standard library. Do not install Node.js in those images.
Keep each proxy check separate from its application check. Other runtime implementations are out of scope here.

## Exec probe examples

These are Kubernetes container fields, not chart values.
Run the probe in the main CDP container, not the proxy container.
Keep the existing readiness and startup probes.

For an explicitly enabled local sidecar:

```yaml
livenessProbe:
  exec:
    command:
      - /code/nodejs/bin/check-cdp-liveness.mjs
      - --proxy-sidecar
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

For an application-only exec probe:

```yaml
livenessProbe:
  exec:
    command: [/code/nodejs/bin/check-cdp-liveness.mjs]
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

Existing central-proxy and disabled-proxy workloads should retain their current HTTP probes.
The application-only example is available when an exec probe is needed; this change does not select it automatically.

In a later chart change, select the combined command only for `httpProxy.enabled: true` and `httpProxy.mode: sidecar`.
An omitted mode means `central`. `enabled: false` disables either mode.
Remove the merged `httpGet` and `tcpSocket` fields when selecting `exec`; a probe can have only one handler.
First confirm that the deployed CDP image contains the executable and its modules.
Do not add this opt-in to a shared configuration for other images.

## Local tests and image verification

From the repository root:

```sh
node --test nodejs/tests/cdp-liveness.test.mjs
docker build -f Dockerfile.node -t posthog-cdp-liveness:local .
docker run --rm --entrypoint /usr/local/bin/node posthog-cdp-liveness:local --version
docker run --rm --network none \
  -e LIVENESS_TEST_DIRECT_EXEC=1 \
  --mount type=bind,src="$PWD/nodejs/tests",dst=/code/nodejs/tests,readonly \
  --entrypoint /usr/local/bin/node posthog-cdp-liveness:local \
  --test /code/nodejs/tests/cdp-liveness.test.mjs
```

The image test uses the packaged entrypoint and modules, with no source mount over them.
It runs as the final image user. The test servers use only loopback.
It covers HTTP failures, malformed responses, refusal, deadlines, and recovery.
The TCP connect deadline uses a simulated stalled socket; loopback cannot reliably produce a connect timeout.
The tests do not run CDP consumers or prove external request recovery.
`pnpm --dir nodejs test:liveness` runs the same suite. The parallel Node.js test command also runs it.

## Dev fault test

This is an operator procedure, not an instruction to deploy from this task.
Use a disposable dev CDP workload with the updated image and a native proxy sidecar.
Confirm application routing support separately before testing real outbound requests.
This change does not add `CANARY_HTTP_PROXY` support.

1. Record the Pod UID, main-container restart count, sidecar restart count, and current health results.
2. Run the combined executable through `kubectl exec` in the main container. Confirm exit 0.
3. Send an approved synthetic request through CDP. Record its success and connection behavior separately from liveness.
4. Cause a sustained local outage with dev fault tooling. Keep the listener or metrics endpoint unavailable across three consecutive probes.
5. Run the executable during the outage. Confirm exit 1 and a fixed failure message.
6. Observe the main-container restart count and Kubernetes probe events. Allow time for probe scheduling and termination grace.
7. Restore the sidecar. Confirm exit 0. Check that CDP resumes synthetic requests without persistent connection errors.
8. After recovery, cause one brief sidecar restart. Restore it before the main container reaches three consecutive failed probes.
9. Confirm the next combined check passes. Check that CDP reconnects and synthetic requests resume without a main-container restart.
10. Remove the fault. Restore the dev configuration and confirm both containers remain healthy.

Use fault tooling that can block loopback traffic in this disposable Pod, or hold the dev sidecar unavailable.
A single container kill is not a sustained fault because Kubernetes restarts the sidecar.
Do not assume the application image contains a shell or fault tools.
Do not run these faults against a central proxy or a production workload.

For sustained failures, Kubernetes restarts the main container after its own liveness failure threshold.
If the outage continues, main-container restarts can repeat and enter restart backoff.
A brief restart between samples can be invisible. One observed failure below the threshold need not restart the main container.
Connection recovery without a main-container restart depends on the application's clients. Verify it with synthetic requests.
If clients do not reconnect, treat that as a separate application defect, not proof that liveness guarantees recovery.

Kubernetes restarts containers independently. This design does not provide an atomic Pod restart.
It does not make the sidecar depend on main-application health.
A successful local check does not prove that the proxy can forward to an external destination.
Keep forwarding and policy tests separate from liveness.
