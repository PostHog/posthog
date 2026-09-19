# fixture for dockerfile-secret-build-arg
FROM debian:bookworm-slim

# ruleid: dockerfile-secret-build-arg
ARG GITHUB_TOKEN

# ruleid: dockerfile-secret-build-arg
ARG SCCACHE_WEBDAV_TOKEN

# ruleid: dockerfile-secret-build-arg
ARG AWS_SECRET_ACCESS_KEY

# ruleid: dockerfile-secret-build-arg
ARG GH_PAT

# ruleid: dockerfile-secret-build-arg
ARG API_KEY=placeholder

# ruleid: dockerfile-secret-build-arg
ARG TOKEN

# ok: dockerfile-secret-build-arg
ARG NODE_VERSION=24.13.0

# ok: dockerfile-secret-build-arg
ARG COMMIT_HASH

# ok: dockerfile-secret-build-arg
ARG SCCACHE_WEBDAV_KEY_PREFIX

# ok: dockerfile-secret-build-arg
ARG PATCH_VERSION=1.2.3

# the safe pattern: the value never reaches image metadata
# ok: dockerfile-secret-build-arg
RUN --mount=type=secret,id=github_token export GITHUB_TOKEN="$(cat /run/secrets/github_token)" && curl -H "Authorization: Bearer $GITHUB_TOKEN" https://example.com