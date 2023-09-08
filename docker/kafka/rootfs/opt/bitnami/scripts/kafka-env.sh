#!/bin/bash
#
# Environment configuration for kafka

# The values for all environment variables will be set in the below order of precedence
# 1. Custom environment variables defined below after Bitnami defaults
# 2. Constants defined in this file (environment variables with no default), i.e. BITNAMI_ROOT_DIR
# 3. Environment variables overridden via external files using *_FILE variables (see below)
# 4. Environment variables set externally (i.e. current Bash context/Dockerfile/userdata)

# Load logging library
# shellcheck disable=SC1090,SC1091
. /opt/bitnami/scripts/liblog.sh

export BITNAMI_ROOT_DIR="/opt/bitnami"
export BITNAMI_VOLUME_DIR="/bitnami"

# Logging configuration
export MODULE="${MODULE:-kafka}"
export BITNAMI_DEBUG="${BITNAMI_DEBUG:-false}"

# By setting an environment variable matching *_FILE to a file path, the prefixed environment
# variable will be overridden with the value specified in that file
kafka_env_vars=(
    ALLOW_PLAINTEXT_LISTENER
    KAFKA_INTER_BROKER_USER
    KAFKA_INTER_BROKER_PASSWORD
    KAFKA_CERTIFICATE_PASSWORD
    KAFKA_TLS_TRUSTSTORE_FILE
    KAFKA_TLS_TYPE
    KAFKA_TLS_CLIENT_AUTH
    KAFKA_OPTS
    KAFKA_CFG_ADVERTISED_LISTENERS
    KAFKA_CFG_LISTENERS
    KAFKA_CFG_ZOOKEEPER_CONNECT
    KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE
    KAFKA_CFG_SASL_ENABLED_MECHANISMS
    KAFKA_CFG_SASL_MECHANISM_INTER_BROKER_PROTOCOL
    KAFKA_CFG_MAX_REQUEST_SIZE
    KAFKA_CFG_MAX_PARTITION_FETCH_BYTES
    KAFKA_ENABLE_KRAFT
    KAFKA_KRAFT_CLUSTER_ID
    KAFKA_ZOOKEEPER_PROTOCOL
    KAFKA_ZOOKEEPER_PASSWORD
    KAFKA_ZOOKEEPER_USER
    KAFKA_ZOOKEEPER_TLS_KEYSTORE_PASSWORD
    KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_PASSWORD
    KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_FILE
    KAFKA_ZOOKEEPER_TLS_VERIFY_HOSTNAME
    KAFKA_ZOOKEEPER_TLS_TYPE
    KAFKA_CLIENT_USERS
    KAFKA_CLIENT_PASSWORDS
    KAFKA_HEAP_OPTS
)
for env_var in "${kafka_env_vars[@]}"; do
    file_env_var="${env_var}_FILE"
    if [[ -n "${!file_env_var:-}" ]]; then
        if [[ -r "${!file_env_var:-}" ]]; then
            export "${env_var}=$(< "${!file_env_var}")"
            unset "${file_env_var}"
        else
            warn "Skipping export of '${env_var}'. '${!file_env_var:-}' is not readable."
        fi
    fi
done
unset kafka_env_vars

# Paths
export KAFKA_BASE_DIR="${BITNAMI_ROOT_DIR}/kafka"
export KAFKA_VOLUME_DIR="/bitnami/kafka"
export KAFKA_DATA_DIR="${KAFKA_VOLUME_DIR}/data"
export KAFKA_CONF_DIR="${KAFKA_BASE_DIR}/config"
export KAFKA_CONF_FILE="${KAFKA_CONF_DIR}/server.properties"
export KAFKA_MOUNTED_CONF_DIR="${KAFKA_VOLUME_DIR}/config"
export KAFKA_CERTS_DIR="${KAFKA_CONF_DIR}/certs"
export KAFKA_INITSCRIPTS_DIR="/docker-entrypoint-initdb.d"
export KAFKA_LOG_DIR="${KAFKA_BASE_DIR}/logs"
export KAFKA_HOME="$KAFKA_BASE_DIR"
export PATH="${KAFKA_BASE_DIR}/bin:${BITNAMI_ROOT_DIR}/java/bin:${PATH}"

# System users (when running with a privileged user)
export KAFKA_DAEMON_USER="kafka"
export KAFKA_DAEMON_GROUP="kafka"

# Kafka runtime settings
export ALLOW_PLAINTEXT_LISTENER="${ALLOW_PLAINTEXT_LISTENER:-no}"
export KAFKA_INTER_BROKER_USER="${KAFKA_INTER_BROKER_USER:-user}"
export KAFKA_INTER_BROKER_PASSWORD="${KAFKA_INTER_BROKER_PASSWORD:-bitnami}"
export KAFKA_CERTIFICATE_PASSWORD="${KAFKA_CERTIFICATE_PASSWORD:-}"
export KAFKA_TLS_TRUSTSTORE_FILE="${KAFKA_TLS_TRUSTSTORE_FILE:-}"
export KAFKA_TLS_TYPE="${KAFKA_TLS_TYPE:-JKS}"
export KAFKA_TLS_CLIENT_AUTH="${KAFKA_TLS_CLIENT_AUTH:-required}"
export KAFKA_OPTS="${KAFKA_OPTS:-}"

# Kafka configuration overrides
export KAFKA_CFG_ADVERTISED_LISTENERS="${KAFKA_CFG_ADVERTISED_LISTENERS:-PLAINTEXT://:9092}"
export KAFKA_CFG_LISTENERS="${KAFKA_CFG_LISTENERS:-PLAINTEXT://:9092}"
export KAFKA_CFG_ZOOKEEPER_CONNECT="${KAFKA_CFG_ZOOKEEPER_CONNECT:-localhost:2181}"
export KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE="${KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE:-true}"
export KAFKA_CFG_SASL_ENABLED_MECHANISMS="${KAFKA_CFG_SASL_ENABLED_MECHANISMS:-PLAIN,SCRAM-SHA-256,SCRAM-SHA-512}"
export KAFKA_CFG_SASL_MECHANISM_INTER_BROKER_PROTOCOL="${KAFKA_CFG_SASL_MECHANISM_INTER_BROKER_PROTOCOL:-}"
export KAFKA_CFG_MAX_REQUEST_SIZE="${KAFKA_CFG_MAX_REQUEST_SIZE:-1048576}"
export KAFKA_CFG_MAX_PARTITION_FETCH_BYTES="${KAFKA_CFG_MAX_PARTITION_FETCH_BYTES:-1048576}"
export KAFKA_ENABLE_KRAFT="${KAFKA_ENABLE_KRAFT:-no}"
export KAFKA_KRAFT_CLUSTER_ID="${KAFKA_KRAFT_CLUSTER_ID:-}"

# ZooKeeper connection settings
export KAFKA_ZOOKEEPER_PROTOCOL="${KAFKA_ZOOKEEPER_PROTOCOL:-PLAINTEXT}"
export KAFKA_ZOOKEEPER_PASSWORD="${KAFKA_ZOOKEEPER_PASSWORD:-}"
export KAFKA_ZOOKEEPER_USER="${KAFKA_ZOOKEEPER_USER:-}"
export KAFKA_ZOOKEEPER_TLS_KEYSTORE_PASSWORD="${KAFKA_ZOOKEEPER_TLS_KEYSTORE_PASSWORD:-}"
export KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_PASSWORD="${KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_PASSWORD:-}"
export KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_FILE="${KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_FILE:-}"
export KAFKA_ZOOKEEPER_TLS_VERIFY_HOSTNAME="${KAFKA_ZOOKEEPER_TLS_VERIFY_HOSTNAME:-true}"
export KAFKA_ZOOKEEPER_TLS_TYPE="${KAFKA_ZOOKEEPER_TLS_TYPE:-JKS}"

# Authentication
export KAFKA_CLIENT_USERS="${KAFKA_CLIENT_USERS:-user}"
export KAFKA_CLIENT_PASSWORDS="${KAFKA_CLIENT_PASSWORDS:-bitnami}"

# Java settings
export KAFKA_HEAP_OPTS="${KAFKA_HEAP_OPTS:--Xmx1024m -Xms1024m}"

# Custom environment variables may be defined below
