#!/bin/bash

# shellcheck disable=SC1091

set -o errexit
set -o nounset
set -o pipefail
# set -o xtrace # Uncomment this line for debugging purpose

# Load libraries
. /opt/bitnami/scripts/libkafka.sh
. /opt/bitnami/scripts/libos.sh

# Load Kafka environment variables
. /opt/bitnami/scripts/kafka-env.sh

if [[ "${KAFKA_CFG_LISTENERS:-}" =~ SASL ]] || [[ "${KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP:-}" =~ SASL ]] || [[ "${KAFKA_ZOOKEEPER_PROTOCOL:-}" =~ SASL ]]; then
    export KAFKA_OPTS="-Djava.security.auth.login.config=${KAFKA_CONF_DIR}/kafka_jaas.conf"
fi

if [[ "${KAFKA_ZOOKEEPER_PROTOCOL:-}" =~ SSL ]]; then
    ZOOKEEPER_SSL_CONFIG=$(zookeeper_get_tls_config)
    export KAFKA_OPTS="$KAFKA_OPTS $ZOOKEEPER_SSL_CONFIG"
fi

flags=("$KAFKA_CONF_FILE")
[[ -z "${KAFKA_EXTRA_FLAGS:-}" ]] || flags=("${flags[@]}" "${KAFKA_EXTRA_FLAGS[@]}")
START_COMMAND=("$KAFKA_HOME/bin/kafka-server-start.sh" "${flags[@]}" "$@")

info "** Starting Kafka **"
if am_i_root; then
    exec gosu "$KAFKA_DAEMON_USER" "${START_COMMAND[@]}"
else
    exec "${START_COMMAND[@]}"
fi
