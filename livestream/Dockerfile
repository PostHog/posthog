FROM golang:1.26.10 AS builder
WORKDIR /code
COPY go.sum go.mod ./
RUN go mod download -x

COPY . ./
RUN go get ./...
RUN go build -v -o /livestream .

# Fetch the GeoLite2-City database that will be used for IP geolocation within Django.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "ca-certificates" \
    "curl" \
    "brotli" \
    && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir share && \
    ( curl -s -L "https://mmdbcdn.posthog.net/" --http1.1 | brotli --decompress --output=/GeoLite2-City.mmdb ) && \
    chmod -R 755 /GeoLite2-City.mmdb

# Losslessly shrink the database by merging identical subtrees of its search tree
# (https://ipinfo.io/blog/how-made-mmdb-files-smaller). Lookups return the same results from a
# smaller file. mmdbshrink compares 1M random addresses per IP family against the original and
# fails on any difference, so keep the original on failure.
# To update: bump the version and copy the new hashes from the GitHub release assets.
ARG MMDBSHRINK_VERSION=1.5.1
ARG MMDBSHRINK_SHA256_AMD64=7a50c451947466ce9bdebd181c272ac3226b725af480447124db29b952c719fc
ARG MMDBSHRINK_SHA256_ARM64=b9da4f6bfb79a6ccf782387adbfe4d0eb7cf947c1950ab8768a31f3f942858d2
RUN ARCH="$(dpkg --print-architecture)" && \
    case "$ARCH" in amd64) SHA="$MMDBSHRINK_SHA256_AMD64" ;; arm64) SHA="$MMDBSHRINK_SHA256_ARM64" ;; *) SHA="" ;; esac && \
    if [ -n "$SHA" ] && \
        curl -fsSL -o /tmp/mmdbshrink.tar.gz \
            "https://github.com/ipinfo/mmdbctl/releases/download/mmdbctl-${MMDBSHRINK_VERSION}/mmdbshrink_${MMDBSHRINK_VERSION}_linux_${ARCH}.tar.gz" && \
        echo "${SHA}  /tmp/mmdbshrink.tar.gz" | sha256sum -c - && \
        tar -xzf /tmp/mmdbshrink.tar.gz -C /tmp && \
        "/tmp/mmdbshrink_${MMDBSHRINK_VERSION}_linux_${ARCH}" /GeoLite2-City.mmdb /tmp/GeoLite2-City.shrunk.mmdb; then \
        mv /tmp/GeoLite2-City.shrunk.mmdb /GeoLite2-City.mmdb; \
    else \
        echo "WARNING: mmdbshrink failed; keeping the original GeoLite2-City.mmdb" >&2; \
    fi && \
    rm -f /tmp/mmdbshrink* /tmp/GeoLite2-City.shrunk.mmdb && \
    chmod 755 /GeoLite2-City.mmdb

FROM ubuntu:24.04
COPY --from=builder /livestream /GeoLite2-City.mmdb /
COPY --from=builder /etc/ssl/certs /etc/ssl/certs
COPY --from=builder /usr/share/ca-certificates /usr/share/ca-certificates

# TODO run as non-root user
# nosemgrep: dockerfile.security.last-user-is-root.last-user-is-root
USER root

CMD ["/livestream"]
