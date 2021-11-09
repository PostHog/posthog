FROM arm64v8/ubuntu:focal

ARG gosu_ver=1.10
ARG DEBIAN_FRONTEND=noninteractive
ARG GIT_TAG="v21.9.2.17-stable"

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
    && wget --progress=bar:force:noscroll "https://github.com/tianon/gosu/releases/download/$gosu_ver/gosu-$(dpkg --print-architecture)" -O /bin/gosu \
    && chmod +x /bin/gosu

RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8
ENV TZ UTC

RUN apt-get -y install git cmake python ninja-build
RUN git clone --depth 1 --shallow-submodules --branch $GIT_TAG --recursive https://github.com/ClickHouse/ClickHouse.git

RUN apt-get -y install clang-12 build-essential
ENV CC clang-12
ENV CXX clang++-12

RUN cd ClickHouse && mkdir build && cd build && cmake ..
RUN cd ClickHouse/build && ninja -j $(nproc)
RUN mv ClickHouse/build/programs/clickhouse* /usr/bin/

RUN mkdir /docker-entrypoint-initdb.d
COPY ./docker_related_config.xml /etc/clickhouse-server/config.d/
COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 9000 8123 9009
VOLUME /var/lib/clickhouse

ENV CLICKHOUSE_CONFIG /etc/clickhouse-server/config.xml

ENTRYPOINT ["/entrypoint.sh"]