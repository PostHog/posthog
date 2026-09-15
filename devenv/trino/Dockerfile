FROM busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0 AS gzip

FROM trinodb/trino:483@sha256:db58cc93e593a2706553745f276bb119c9810e69918be56ecde088ba7ccb0534

USER root

COPY --from=gzip /bin/busybox /usr/local/bin/busybox

ARG BRIKK_CONNECTOR_VERSION=483-0.2.0
ARG BRIKK_CONNECTOR_SHA256=b8967c47b940c82d357c657c743b703aec7d9523a3ed2213b356ab7424729450

RUN curl --fail --location --silent --show-error \
      "https://github.com/brikk/trino-ducklake/releases/download/v${BRIKK_CONNECTOR_VERSION}/trino-ducklake-${BRIKK_CONNECTOR_VERSION}.tar.gz" \
      --output /tmp/trino-ducklake.tar.gz \
    && echo "${BRIKK_CONNECTOR_SHA256}  /tmp/trino-ducklake.tar.gz" | sha256sum --check --status \
    && mkdir -p /usr/lib/trino/plugin/ducklake \
    && /usr/local/bin/busybox gunzip --stdout /tmp/trino-ducklake.tar.gz | tar --extract --file - --strip-components=1 --directory /usr/lib/trino/plugin/ducklake \
    && rm /tmp/trino-ducklake.tar.gz \
    && chown -R trino:trino /usr/lib/trino/plugin/ducklake

USER trino
