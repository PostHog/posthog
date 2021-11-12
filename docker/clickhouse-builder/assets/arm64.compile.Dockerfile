FROM ubuntu:focal AS clickhouse_codebase
ARG CLICKHOUSE_TAG="v21.6.5.37-stable"
ARG DEBIAN_FRONTEND=noninteractive

# Install dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get install --no-install-recommends -y \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --shallow-submodules --branch "${CLICKHOUSE_TAG}" --recursive https://github.com/ClickHouse/ClickHouse.git


FROM  arm64v8/ubuntu:focal as builder

ARG gosu_ver=1.10
ARG DEBIAN_FRONTEND=noninteractive

COPY --from=clickhouse_codebase /ClickHouse /ClickHouse

ENV LLVM_VERSION 10

RUN apt-get update && apt-get -y install cmake python ninja-build lsb-release wget software-properties-common build-essential libc6-dev
RUN wget https://apt.llvm.org/llvm.sh && \
    chmod +x llvm.sh && \
    ./llvm.sh $LLVM_VERSION
RUN apt-get update && apt-get -y install llvm-$LLVM_VERSION

WORKDIR /ClickHouse
RUN mkdir -p build-aarch64/cmake/toolchain/linux-aarch64 && \
wget 'https://developer.arm.com/-/media/Files/downloads/gnu-a/8.3-2019.03/binrel/gcc-arm-8.3-2019.03-x86_64-aarch64-linux-gnu.tar.xz?revision=2e88a73f-d233-4f96-b1f4-d8b36e9bb0b9&la=en' -O gcc-arm-8.3-2019.03-x86_64-aarch64-linux-gnu.tar.xz && \
tar xJf gcc-arm-8.3-2019.03-x86_64-aarch64-linux-gnu.tar.xz -C build-aarch64/cmake/toolchain/linux-aarch64 --strip-components=1
#cp -r build-aarch64/cmake/toolchain/linux-aarch64/ cmake/toolchain/

WORKDIR build-arm64
# "v21.6.5.37-stable" does not build with llvm 13. later versions do
RUN CC=clang-$LLVM_VERSION CXX=clang++-$LLVM_VERSION cmake .. -DGLIBC_COMPATIBILITY=OFF && \
ninja  -j $(nproc)

FROM arm64v8/ubuntu:focal

RUN groupadd -r clickhouse --gid=101 \
    && useradd -r -g clickhouse --uid=101 --home-dir=/var/lib/clickhouse --shell=/bin/bash clickhouse

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        apt-transport-https \
        ca-certificates \
        dirmngr \
        gnupg \
        locales \
        wget \
        tzdata \

RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8
ENV TZ UTC

COPY --from=builder /ClickHouse/build-arm64/programs/clickhouse* /usr/bin/

RUN mkdir /docker-entrypoint-initdb.d
COPY ./docker_related_config.xml /etc/clickhouse-server/config.d/
COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 9000 8123 9009
VOLUME /var/lib/clickhouse

ENV CLICKHOUSE_CONFIG /etc/clickhouse-server/config.xml

ENTRYPOINT ["/entrypoint.sh"]