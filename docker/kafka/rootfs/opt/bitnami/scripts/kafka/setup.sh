#!/bin/bash

# shellcheck disable=SC1091

set -o errexit
set -o nounset
set -o pipefail
# set -o xtrace # Uncomment this line for debugging purpose

# Load libraries
. /opt/bitnami/scripts/libfs.sh
. /opt/bitnami/scripts/libos.sh
. /opt/bitnami/scripts/libkafka.sh

# Load Kafka environment variables
. /opt/bitnami/scripts/kafka-env.sh

# Map Kafka environment variables
kafka_create_alias_environment_variables
if [[ -z "${KAFKA_CFG_BROKER_ID:-}" ]]; then
    if [[ -n "${BROKER_ID_COMMAND:-}" ]]; then
        KAFKA_CFG_BROKER_ID="$(eval "${BROKER_ID_COMMAND:-}")"
        export KAFKA_CFG_BROKER_ID
    elif ! is_boolean_yes "$KAFKA_ENABLE_KRAFT"; then
        # By default auto allocate broker ID unless KRaft is enabled
        export KAFKA_CFG_BROKER_ID=-1
    fi
fi
# Set the default tuststore locations
kafka_configure_default_truststore_locations
# Ensure Kafka environment variables are valid
kafka_validate
# Ensure Kafka user and group exist when running as 'root'
if am_i_root; then
    ensure_user_exists "$KAFKA_DAEMON_USER" --group "$KAFKA_DAEMON_GROUP"
    KAFKA_OWNERSHIP_USER="$KAFKA_DAEMON_USER"
else
    KAFKA_OWNERSHIP_USER=""
fi
# Ensure directories used by Kafka exist and have proper ownership and permissions
for dir in "$KAFKA_LOG_DIR" "$KAFKA_CONF_DIR" "$KAFKA_MOUNTED_CONF_DIR" "$KAFKA_VOLUME_DIR" "$KAFKA_DATA_DIR"; do
    ensure_dir_exists "$dir" "$KAFKA_OWNERSHIP_USER"
done
# Ensure Kafka is initialized
kafka_initialize
# If KRaft is enabled initialize
if is_boolean_yes "$KAFKA_ENABLE_KRAFT"; then
    kraft_initialize
fi
# Ensure custom initialization scripts are executed
kafka_custom_init_scripts
