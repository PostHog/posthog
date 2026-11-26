#!/bin/sh
# Starts the fake PostHog proxy and writes one Dockerfile per scenario for StuntHog environments.
#
#   hog/evals/mock/start.sh            # hog from the latest release
#   HOG_VERSION=0.2.0 hog/evals/mock/start.sh
#
# Each scenario listens on its own port, and its Dockerfile points HTTPS_PROXY there.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
state="$here/../.generated"
mkdir -p "$state/ca" "$state/logs" "$state/env"

version="${HOG_VERSION:-$(curl -fsSL https://releases.posthog.com/hog/latest/manifest.json | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' | head -1)}"
[ -n "$version" ] || { echo "Couldn't read the latest hog version. Set HOG_VERSION." >&2; exit 1; }

# The mock answers hog's update check with this version, so a release during a run doesn't stop setup.
curl -fsSL "https://releases.posthog.com/hog/v$version/manifest.json" -o "$state/manifest.json"

# `hog api` reads its tool catalog from PostHog. The mock serves this copy, so runs don't reach PostHog.
curl -fsSL https://us.posthog.com/api/cli/catalog.json -o "$state/catalog.json"

# The proxy listens on loopback only, so other machines on the network can't relay through it. Docker
# Desktop forwards host.docker.internal to it. On Linux Docker Engine, set HOG_MOCK_BIND to the docker0
# address, such as 172.17.0.1, and HOG_MOCK_HOST to the same address.
bind=${HOG_MOCK_BIND:-127.0.0.1}
mock_host=${HOG_MOCK_HOST:-host.docker.internal}

docker rm -f hog-mock >/dev/null 2>&1 || true
docker run -d --name hog-mock \
    -p "$bind:18080-18083:18080-18083" \
    -v "$state/ca:/home/mitmproxy/.mitmproxy" \
    -v "$state/logs:/logs" \
    -v "$here:/mock/src:ro" \
    -v "$state/manifest.json:/mock/manifest.json:ro" \
    -v "$state/catalog.json:/mock/catalog.json:ro" \
    mitmproxy/mitmproxy:12 \
    mitmdump --quiet \
        --set connection_strategy=lazy \
        --mode regular@18080 --mode regular@18081 --mode regular@18082 --mode regular@18083 \
        --allow-hosts '^(us|eu)(\.i)?\.posthog\.com(:443)?$' \
        --allow-hosts '^releases\.posthog\.com(:443)?$' \
        -s /mock/src/addon.py >/dev/null

# connection_strategy=lazy: mitmproxy reaches the real host only for a request the addon passes through,
# so a run doesn't depend on PostHog being reachable.
# The addon's folder is mounted rather than the file: a formatter or git rewrites the file as a new inode,
# and a single-file mount would keep the old one, leaving mitmproxy to pass every request to the real PostHog.

# mitmproxy writes its CA on first start.
for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ -f "$state/ca/mitmproxy-ca-cert.pem" ] && break
    sleep 1
done
cp "$state/ca/mitmproxy-ca-cert.pem" "$state/env/mock-ca.crt"

for pair in approve:18080 never:18081 denied:18082 quiet:18083; do
    name=${pair%%:*}
    port=${pair##*:}
    cat >"$state/env/Dockerfile.$name" <<EOF
FROM node:22-bookworm-slim

RUN apt-get update \\
    && apt-get install --yes --no-install-recommends ca-certificates curl git ripgrep python3 python3-pip python3-venv \\
    && rm -rf /var/lib/apt/lists/*

# Python apps get a virtualenv outside the workspace: StuntHog can't save the symlinks of one inside it.
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --quiet flask==3.1.2
ENV PATH=/opt/venv/bin:\$PATH VIRTUAL_ENV=/opt/venv

# The fake PostHog (scenario: $name) answers for us/eu.posthog.com through this proxy.
COPY mock-ca.crt /usr/local/share/ca-certificates/hog-mock.crt
RUN update-ca-certificates
ENV HTTPS_PROXY=http://$mock_host:$port \\
    HTTP_PROXY=http://$mock_host:$port \\
    NO_PROXY=localhost,127.0.0.1,registry.npmjs.org,api.anthropic.com,statsig.anthropic.com,openrouter.ai,api.openai.com,chatgpt.com \\
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \\
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \\
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# hog and hog-worker from the release, installed with its install script. The install skips the proxy,
# so the image builds from the real release even when the mock isn't running.
RUN unset HTTPS_PROXY HTTP_PROXY \\
    && curl -fsSL https://releases.posthog.com/hog/install.sh -o /tmp/install-hog.sh \\
    && HOG_INSTALL_DIR=/usr/local/bin sh /tmp/install-hog.sh --version $version \\
    && rm /tmp/install-hog.sh \\
    && hog --version && test -x /usr/local/bin/hog-worker
EOF
done

echo "Fake PostHog is running with hog $version."
echo "Dockerfiles: $state/env"
echo "Requests:    $state/logs/requests.jsonl"
