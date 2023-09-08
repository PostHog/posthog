FROM docker.io/bitnami/minideb:bullseye

ARG JAVA_EXTRA_SECURITY_DIR="/bitnami/java/extra-security"
ARG TARGETARCH

ENV HOME="/" \
    OS_ARCH="${TARGETARCH:-amd64}" \
    OS_FLAVOUR="debian-11" \
    OS_NAME="linux"

COPY prebuildfs /
# Install required system packages and dependencies
RUN install_packages acl ca-certificates curl gzip libc6 procps tar zlib1g
RUN . /opt/bitnami/scripts/libcomponent.sh && component_unpack "wait-for-port" "1.0.6-13"
RUN . /opt/bitnami/scripts/libcomponent.sh && component_unpack "render-template" "1.0.5-13"
RUN if [ "$TARGETARCH" = "amd64" ]; then \
        curl --remote-name --silent --show-error --fail https://download.oracle.com/java/17/archive/jdk-17.0.2_linux-x64_bin.tar.gz; \
        tar xf jdk-17.0.2_linux-x64_bin.tar.gz; \
        mv jdk-17.0.2 /opt/bitnami/java; \
        rm jdk-17.0.2_linux-x64_bin.tar.gz; \
    elif [ "$TARGETARCH" = "arm64" ]; then \
        curl --remote-name --silent --show-error --fail https://download.oracle.com/java/17/archive/jdk-17.0.2_linux-aarch64_bin.tar.gz; \
        tar xf jdk-17.0.2_linux-aarch64_bin.tar.gz; \
        mv jdk-17.0.2 /opt/bitnami/java; \
        rm jdk-17.0.2_linux-aarch64_bin.tar.gz; \
    else \
        echo "Only arm64 and amd64 are supported." && exit 1; \
    fi
RUN curl --remote-name --silent --show-error --fail https://archive.apache.org/dist/kafka/2.8.2/kafka_2.12-2.8.2.tgz; \
    tar xf kafka_2.12-2.8.2.tgz; \
    mv kafka_2.12-2.8.2 /opt/bitnami/kafka; \
    rm kafka_2.12-2.8.2.tgz
RUN apt-get update && apt-get upgrade -y && \
    rm -r /var/lib/apt/lists /var/cache/apt/archives
RUN chmod g+rwX /opt/bitnami
RUN ln -s /opt/bitnami/scripts/kafka/entrypoint.sh /entrypoint.sh
RUN ln -s /opt/bitnami/scripts/kafka/run.sh /run.sh

COPY rootfs /
RUN /opt/bitnami/scripts/java/postunpack.sh
RUN /opt/bitnami/scripts/kafka/postunpack.sh
ENV APP_VERSION="2" \
    BITNAMI_APP_NAME="kafka" \
    JAVA_HOME="/opt/bitnami/java" \
    PATH="/opt/bitnami/java/bin:/opt/bitnami/common/bin:/opt/bitnami/kafka/bin:$PATH"

EXPOSE 9092

USER 1001
ENTRYPOINT [ "/opt/bitnami/scripts/kafka/entrypoint.sh" ]
CMD [ "/opt/bitnami/scripts/kafka/run.sh" ]
