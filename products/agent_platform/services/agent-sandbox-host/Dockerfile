# Canonical sandbox-host image used by BOTH the Docker and Modal pools.
#
#   Docker pool: runs the image with `docker run -v <workdir>:/workdir
#                <image> node /sandbox/host.js`. host.js writes
#                /workdir/host.alive on boot so the runner-side pool knows
#                the container is ready before issuing the first dispatch.
#
#   Modal pool:  runs the image with no foreground command — Modal's default
#                is "sleep indefinitely until timeout or terminate". host.js
#                is never invoked; the dispatcher is exec'd per tool call.
#
# Both pools converge on /sandbox/dispatch.js (the same per-invoke handler)
# and the same /workdir/{tools,nonces.json,req-N.json,res-N.json} wire format.
# Modal additionally `filesystem.writeText`s the dispatcher per acquire as a
# defensive measure — works against this canonical image (overwrites
# identical content) AND against a plain node base if the chart ever points
# at one.

# Pinned to a specific minor (matches services/agents/Dockerfile's
# NODE_VERSION) so the base image can't silently shift between builds.
FROM node:24.13.0-alpine

# Run as a non-root user inside the container. Defense in depth even though
# the Docker pool uses --network=none and Modal sandboxes are isolated by
# default.
RUN addgroup -S sandbox && adduser -S -G sandbox sandbox

# Bake the per-invoke dispatcher + the long-lived host. Both pure Node
# stdlib, no install step — keeps the image thin.
COPY src/host.js /sandbox/host.js
COPY src/dispatch.js /sandbox/dispatch.js
RUN chmod +x /sandbox/host.js /sandbox/dispatch.js

# /workdir is the bind-mount target (Docker) or the in-sandbox writable
# scratch (Modal). The runner-side pool lays out /workdir/tools/<id>/* and
# /workdir/nonces.json per session before any dispatch.
RUN mkdir -p /workdir && chown sandbox:sandbox /workdir
USER sandbox
WORKDIR /workdir

# No CMD — Modal needs an idle entrypoint (its default is "sleep
# indefinitely"); the Docker pool overrides with `node /sandbox/host.js`
# explicitly. Leaving CMD unset keeps the two paths symmetric.
