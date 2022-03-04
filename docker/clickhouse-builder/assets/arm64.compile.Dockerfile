#
# We use this Dockerfile to build a ClickHouse image for ARM64
#
# This is needed till https://github.com/ClickHouse/ClickHouse/issues/22222
# gets fixed. Please use this image only for local development.
#
FROM arm64v8/ubuntu:focal AS builder

ARG DEBIAN_FRONTEND=noninteractive
ARG CLICKHOUSE_TAG="v21.11.11.1-stable"

RUN apt-get update && apt-get install -y git cmake python ninja-build
RUN git clone --depth 1 --shallow-submodules --branch $CLICKHOUSE_TAG --recursive https://github.com/ClickHouse/ClickHouse.git

RUN apt-get install -y clang-12 build-essential
ENV CC clang-12
ENV CXX clang++-12

RUN cd ClickHouse && mkdir build && cd build && cmake ..
RUN cd ClickHouse/build && ninja -j $(nproc)

# ----

FROM arm64v8/ubuntu:focal

ARG DEBIAN_FRONTEND=noninteractive
ARG GOSU_VER="1.14"

RUN groupadd -r clickhouse --gid=101 \
    && useradd -r -g clickhouse --uid=101 --home-dir=/var/lib/clickhouse --shell=/bin/bash clickhouse \
    && apt-get update \
    && apt-get install --yes --no-install-recommends \
        apt-transport-https \
        ca-certificates \
        dirmngr \
        gnupg \
        locales \
        wget \
        tzdata \
    && wget --progress=bar:force:noscroll "https://github.com/tianon/gosu/releases/download/$GOSU_VER/gosu-$(dpkg --print-architecture)" -O /bin/gosu \
    && chmod +x /bin/gosu

COPY --from=builder ClickHouse/build/programs/clickhouse* /usr/bin/

# The code below is copy/pasted from https://github.com/ClickHouse/ClickHouse/blob/63db0f7bac144038a85b177a1341b3fce2c4eaae/docker/server/Dockerfile#L105-L122
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8
ENV TZ UTC

RUN mkdir /docker-entrypoint-initdb.d

COPY docker_related_config.xml /etc/clickhouse-server/config.d/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 9000 8123 9009
VOLUME /var/lib/clickhouse

ENV CLICKHOUSE_CONFIG /etc/clickhouse-server/config.xml

ENTRYPOINT ["/entrypoint.sh"]
