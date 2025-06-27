FROM golang:1.24.4 AS builder
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

FROM ubuntu:24.04
COPY --from=builder /livestream /GeoLite2-City.mmdb /
COPY --from=builder /etc/ssl/certs /etc/ssl/certs
COPY --from=builder /usr/share/ca-certificates /usr/share/ca-certificates

CMD ["/livestream"]
