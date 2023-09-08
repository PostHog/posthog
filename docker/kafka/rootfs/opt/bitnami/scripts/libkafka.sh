#!/bin/bash
#
# Bitnami Kafka library

# shellcheck disable=SC1090,SC1091

# Load Generic Libraries
. /opt/bitnami/scripts/libfile.sh
. /opt/bitnami/scripts/libfs.sh
. /opt/bitnami/scripts/liblog.sh
. /opt/bitnami/scripts/libos.sh
. /opt/bitnami/scripts/libvalidations.sh
. /opt/bitnami/scripts/libservice.sh

# Functions

########################
# Set a configuration setting value to a file
# Globals:
#   None
# Arguments:
#   $1 - file
#   $2 - key
#   $3 - values (array)
# Returns:
#   None
#########################
kafka_common_conf_set() {
    local file="${1:?missing file}"
    local key="${2:?missing key}"
    shift
    shift
    local values=("$@")

    if [[ "${#values[@]}" -eq 0 ]]; then
        stderr_print "missing value"
        return 1
    elif [[ "${#values[@]}" -ne 1 ]]; then
        for i in "${!values[@]}"; do
            kafka_common_conf_set "$file" "${key[$i]}" "${values[$i]}"
        done
    else
        value="${values[0]}"
        # Check if the value was set before
        if grep -q "^[#\\s]*$key\s*=.*" "$file"; then
            # Update the existing key
            replace_in_file "$file" "^[#\\s]*${key}\s*=.*" "${key}=${value}" false
        else
            # Add a new key
            printf '\n%s=%s' "$key" "$value" >>"$file"
        fi
    fi
}

########################
# Backwards compatibility measure to configure the TLS truststore locations
# Globals:
#   KAFKA_CONF_FILE
# Arguments:
#   None
# Returns:
#   None
#########################
kafka_configure_default_truststore_locations() {
    # Backwards compatibility measure to allow custom truststore locations but at the same time not disrupt
    # the UX that the previous version of the containers and the helm chart have.
    # Context: The chart and containers by default assumed that the truststore location was KAFKA_CERTS_DIR/kafka.truststore.jks or KAFKA_MOUNTED_CONF_DIR/certs/kafka.truststore.jks.
    # Because of this, we could not use custom certificates in different locations (use case: A custom base image that already has a truststore). Changing the logic to allow custom
    # locations implied major changes in the current user experience (which only required to mount certificates at the assumed location). In order to maintain this compatibility we need
    # use this logic that sets the KAFKA_TLS_*_FILE variables to the previously assumed locations in case it is not set

    # Kafka truststore
    if { [[ "${KAFKA_CFG_LISTENERS:-}" =~ SSL ]] || [[ "${KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP:-}" =~ SSL ]]; } && is_empty_value "$KAFKA_TLS_TRUSTSTORE_FILE"; then
        local kafka_truststore_filename="kafka.truststore.jks"
        [[ "$KAFKA_TLS_TYPE" = "PEM" ]] && kafka_truststore_filename="kafka.truststore.pem"
        if [[ -f "${KAFKA_CERTS_DIR}/${kafka_truststore_filename}" ]]; then
            # Mounted in /opt/bitnami/kafka/conf/certs
            export KAFKA_TLS_TRUSTSTORE_FILE="${KAFKA_CERTS_DIR}/${kafka_truststore_filename}"
        else
            # Mounted in /bitnami/kafka/conf/certs
            export KAFKA_TLS_TRUSTSTORE_FILE="${KAFKA_MOUNTED_CONF_DIR}/certs/${kafka_truststore_filename}"
        fi
    fi
    # Zookeeper truststore
    if [[ "${KAFKA_ZOOKEEPER_PROTOCOL:-}" =~ SSL ]] && is_empty_value "$KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_FILE"; then
        local zk_truststore_filename="zookeeper.truststore.jks"
        [[ "$KAFKA_ZOOKEEPER_TLS_TYPE" = "PEM" ]] && zk_truststore_filename="zookeeper.truststore.pem"
        if [[ -f "${KAFKA_CERTS_DIR}/${zk_truststore_filename}" ]]; then
            # Mounted in /opt/bitnami/kafka/conf/certs
            export KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_FILE="${KAFKA_CERTS_DIR}/${zk_truststore_filename}"
        else
            # Mounted in /bitnami/kafka/conf/certs
            export KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_FILE="${KAFKA_MOUNTED_CONF_DIR}/certs/${zk_truststore_filename}"
        fi
    fi
}

########################
# Set a configuration setting value to server.properties
# Globals:
#   KAFKA_CONF_FILE
# Arguments:
#   $1 - key
#   $2 - values (array)
# Returns:
#   None
#########################
kafka_server_conf_set() {
    kafka_common_conf_set "$KAFKA_CONF_FILE" "$@"
}

########################
# Set a configuration setting value to producer.properties and consumer.properties
# Globals:
#   KAFKA_CONF_DIR
# Arguments:
#   $1 - key
#   $2 - values (array)
# Returns:
#   None
#########################
kafka_producer_consumer_conf_set() {
    kafka_common_conf_set "$KAFKA_CONF_DIR/producer.properties" "$@"
    kafka_common_conf_set "$KAFKA_CONF_DIR/consumer.properties" "$@"
}

########################
# Create alias for environment variable, so both can be used
# Globals:
#   None
# Arguments:
#   $1 - Alias environment variable name
#   $2 - Original environment variable name
# Returns:
#   None
#########################
kafka_declare_alias_env() {
    local -r alias="${1:?missing environment variable alias}"
    local -r original="${2:?missing original environment variable}"
    if printenv "${original}" >/dev/null; then
        export "$alias"="${!original:-}"
    fi
}

########################
# Map Kafka legacy environment variables to the new names
# Globals:
#   KAFKA_*
# Arguments:
#   None
# Returns:
#   None
#########################
kafka_create_alias_environment_variables() {
    suffixes=(
        "ADVERTISED_LISTENERS"
        "BROKER_ID"
        "DEFAULT_REPLICATION_FACTOR"
        "DELETE_TOPIC_ENABLE"
        "INTER_BROKER_LISTENER_NAME"
        "LISTENERS"
        "LISTENER_SECURITY_PROTOCOL_MAP"
        "LOG_DIRS"
        "LOG_FLUSH_INTERVAL_MESSAGES"
        "LOG_FLUSH_INTERVAL_MS"
        "LOG_MESSAGE_FORMAT_VERSION"
        "LOG_RETENTION_BYTES"
        "LOG_RETENTION_CHECK_INTERVALS_MS"
        "LOG_RETENTION_HOURS"
        "LOG_SEGMENT_BYTES"
        "MESSAGE_MAX_BYTES"
        "NUM_IO_THREADS"
        "NUM_NETWORK_THREADS"
        "NUM_PARTITIONS"
        "NUM_RECOVERY_THREADS_PER_DATA_DIR"
        "OFFSETS_TOPIC_REPLICATION_FACTOR"
        "SOCKET_RECEIVE_BUFFER_BYTES"
        "SOCKET_REQUEST_MAX_BYTES"
        "SOCKET_SEND_BUFFER_BYTES"
        "SSL_ENDPOINT_IDENTIFICATION_ALGORITHM"
        "TRANSACTION_STATE_LOG_MIN_ISR"
        "TRANSACTION_STATE_LOG_REPLICATION_FACTOR"
        "ZOOKEEPER_CONNECT"
        "ZOOKEEPER_CONNECTION_TIMEOUT_MS"
    )
    kafka_declare_alias_env "KAFKA_CFG_LOG_DIRS" "KAFKA_LOGS_DIRS"
    kafka_declare_alias_env "KAFKA_CFG_LOG_SEGMENT_BYTES" "KAFKA_SEGMENT_BYTES"
    kafka_declare_alias_env "KAFKA_CFG_MESSAGE_MAX_BYTES" "KAFKA_MAX_MESSAGE_BYTES"
    kafka_declare_alias_env "KAFKA_CFG_ZOOKEEPER_CONNECTION_TIMEOUT_MS" "KAFKA_ZOOKEEPER_CONNECT_TIMEOUT_MS"
    kafka_declare_alias_env "KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE" "KAFKA_AUTO_CREATE_TOPICS_ENABLE"
    kafka_declare_alias_env "KAFKA_CLIENT_USERS" "KAFKA_BROKER_USER"
    kafka_declare_alias_env "KAFKA_CLIENT_PASSWORDS" "KAFKA_BROKER_PASSWORD"
    for s in "${suffixes[@]}"; do
        kafka_declare_alias_env "KAFKA_CFG_${s}" "KAFKA_${s}"
    done
}

########################
# Validate settings in KAFKA_* env vars
# Globals:
#   KAFKA_*
# Arguments:
#   None
# Returns:
#   None
#########################
kafka_validate() {
    debug "Validating settings in KAFKA_* env vars..."
    local error_code=0
    local internal_port
    local client_port

    # Auxiliary functions
    print_validation_error() {
        error "$1"
        error_code=1
    }
    check_allowed_listener_port() {
        local -r total="$#"
        for i in $(seq 1 "$((total - 1))"); do
            for j in $(seq "$((i + 1))" "$total"); do
                if (("${!i}" == "${!j}")); then
                    print_validation_error "There are listeners bound to the same port"
                fi
            done
        done
    }
    check_conflicting_listener_ports() {
        local validate_port_args=()
        ! am_i_root && validate_port_args+=("-unprivileged")
        if ! err=$(validate_port "${validate_port_args[@]}" "$1"); then
            print_validation_error "An invalid port was specified in the environment variable KAFKA_CFG_LISTENERS: $err"
        fi
    }
    check_multi_value() {
        if [[ " ${2} " != *" ${!1} "* ]]; then
            print_validation_error "The allowed values for ${1} are: ${2}"
        fi
    }

    if is_boolean_yes "$KAFKA_ENABLE_KRAFT"; then
        if [[ -n "$KAFKA_CFG_BROKER_ID" ]]; then
            warn "KAFKA_CFG_BROKER_ID Must match what is set in KAFKA_CFG_CONTROLLER_QUORUM_VOTERS"
        else
            print_validation_error "KRaft requires KAFKA_CFG_BROKER_ID to be set for the quorum controller"
        fi
        if [[ -n "$KAFKA_CFG_CONTROLLER_QUORUM_VOTERS" ]]; then
            warn "KAFKA_CFG_CONTROLLER_QUORUM_VOTERS must match brokers set with KAFKA_CFG_BROKER_ID"
        else
            print_validation_error "KRaft requires KAFKA_CFG_CONTROLLER_QUORUM_VOTERS to be set"
        fi
        if [[ -z "$KAFKA_CFG_CONTROLLER_LISTENER_NAMES" ]]; then
            print_validation_error "KRaft requires KAFKA_CFG_CONTROLLER_LISTENER_NAMES to be set"
        fi
        if [[ -n "$KAFKA_CFG_PROCESS_ROLES" ]]; then
            warn "KAFKA_CFG_PROCESS_ROLES must include 'controller' for KRaft"
        else
            print_validation_error "KAFKA_CFG_PROCESS_ROLES must be set to enable KRaft m,model"
        fi
        if [[ -n "$KAFKA_CFG_LISTENERS" ]]; then
            warn "KAFKA_CFG_LISTENERS must include a listener for CONTROLLER"
        else
            print_validation_error "KRaft requires KAFKA_CFG_LISTENERS to be set"
        fi
    fi

    if [[ ${KAFKA_CFG_LISTENERS:-} =~ INTERNAL://:([0-9]*) ]]; then
        internal_port="${BASH_REMATCH[1]}"
        check_allowed_listener_port "$internal_port"
    fi
    if [[ ${KAFKA_CFG_LISTENERS:-} =~ CLIENT://:([0-9]*) ]]; then
        client_port="${BASH_REMATCH[1]}"
        check_allowed_listener_port "$client_port"
    fi
    [[ -n ${internal_port:-} && -n ${client_port:-} ]] && check_conflicting_listener_ports "$internal_port" "$client_port"
    if [[ -n "${KAFKA_PORT_NUMBER:-}" ]] || [[ -n "${KAFKA_CFG_PORT:-}" ]]; then
        warn "The environment variables KAFKA_PORT_NUMBER and KAFKA_CFG_PORT are deprecated, you can specify the port number to use for each listener using the KAFKA_CFG_LISTENERS environment variable instead."
    fi

    read -r -a users <<<"$(tr ',;' ' ' <<<"${KAFKA_CLIENT_USERS}")"
    read -r -a passwords <<<"$(tr ',;' ' ' <<<"${KAFKA_CLIENT_PASSWORDS}")"
    if [[ "${#users[@]}" -ne "${#passwords[@]}" ]]; then
        print_validation_error "Specify the same number of passwords on KAFKA_CLIENT_PASSWORDS as the number of users on KAFKA_CLIENT_USERS!"
    fi

    if is_boolean_yes "$ALLOW_PLAINTEXT_LISTENER"; then
        warn "You set the environment variable ALLOW_PLAINTEXT_LISTENER=$ALLOW_PLAINTEXT_LISTENER. For safety reasons, do not use this flag in a production environment."
    fi
    if [[ "${KAFKA_CFG_LISTENERS:-}" =~ SSL ]] || [[ "${KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP:-}" =~ SSL ]]; then
        if [[ "$KAFKA_TLS_TYPE" = "JKS" ]] &&
            { [[ ! -f "${KAFKA_CERTS_DIR}/kafka.keystore.jks" ]] || [[ ! -f "$KAFKA_TLS_TRUSTSTORE_FILE" ]]; } &&
            { [[ ! -f "${KAFKA_MOUNTED_CONF_DIR}/certs/kafka.keystore.jks" ]] || [[ ! -f "$KAFKA_TLS_TRUSTSTORE_FILE" ]]; }; then
            print_validation_error "In order to configure the TLS encryption for Kafka with JKS certs you must mount your kafka.keystore.jks and kafka.truststore.jks certs to the ${KAFKA_MOUNTED_CONF_DIR}/certs directory."
        elif [[ "$KAFKA_TLS_TYPE" = "PEM" ]] &&
            { [[ ! -f "${KAFKA_CERTS_DIR}/kafka.keystore.pem" ]] || [[ ! -f "${KAFKA_CERTS_DIR}/kafka.keystore.key" ]] || [[ ! -f "$KAFKA_TLS_TRUSTSTORE_FILE" ]]; } &&
            { [[ ! -f "${KAFKA_MOUNTED_CONF_DIR}/certs/kafka.keystore.pem" ]] || [[ ! -f "${KAFKA_MOUNTED_CONF_DIR}/certs/kafka.keystore.key" ]] || [[ ! -f "$KAFKA_TLS_TRUSTSTORE_FILE" ]]; }; then
            print_validation_error "In order to configure the TLS encryption for Kafka with PEM certs you must mount your kafka.keystore.pem, kafka.keystore.key and kafka.truststore.pem certs to the ${KAFKA_MOUNTED_CONF_DIR}/certs directory."
        fi
    elif [[ "${KAFKA_CFG_LISTENERS:-}" =~ SASL ]] || [[ "${KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP:-}" =~ SASL ]]; then
        if [[ -z "$KAFKA_CLIENT_PASSWORDS" && -z "$KAFKA_INTER_BROKER_PASSWORD" ]]; then
            print_validation_error "In order to configure SASL authentication for Kafka, you must provide the SASL credentials. Set the environment variables KAFKA_CLIENT_USERS and KAFKA_CLIENT_PASSWORDS, to configure the credentials for SASL authentication with clients, or set the environment variables KAFKA_INTER_BROKER_USER and KAFKA_INTER_BROKER_PASSWORD, to configure the credentials for SASL authentication between brokers."
        fi
    elif ! is_boolean_yes "$ALLOW_PLAINTEXT_LISTENER"; then
        print_validation_error "The KAFKA_CFG_LISTENERS environment variable does not configure a secure listener. Set the environment variable ALLOW_PLAINTEXT_LISTENER=yes to allow the container to be started with a plaintext listener. This is only recommended for development."
    fi
    if ! is_boolean_yes "$KAFKA_ENABLE_KRAFT"; then
        if [[ "${KAFKA_ZOOKEEPER_PROTOCOL}" =~ SSL ]]; then
            if [[ "$KAFKA_ZOOKEEPER_TLS_TYPE" = "JKS" ]] &&
                [[ ! -f "$KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_FILE" ]]; then
                print_validation_error "In order to configure the TLS encryption for Zookeeper with JKS certs you must mount your zookeeper.truststore.jks cert to the ${KAFKA_MOUNTED_CONF_DIR}/certs directory."
            elif [[ "$KAFKA_ZOOKEEPER_TLS_TYPE" = "PEM" ]] &&
                [[ ! -f "$KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_FILE" ]]; then
                print_validation_error "In order to configure the TLS encryption for Zookeeper with PEM certs you must mount your zookeeper.truststore.pem cert to the ${KAFKA_MOUNTED_CONF_DIR}/certs directory."
            fi
            if [[ "$KAFKA_ZOOKEEPER_TLS_TYPE" = "JKS" ]] &&
                [[ ! -f "${KAFKA_CERTS_DIR}/zookeeper.keystore.jks" ]] && [[ ! -f "${KAFKA_MOUNTED_CONF_DIR}/certs/zookeeper.keystore.jks" ]]; then
                warn "In order to configure the mTLS for Zookeeper with JKS certs you must mount your zookeeper.keystore.jks cert to the ${KAFKA_MOUNTED_CONF_DIR}/certs directory."
            elif [[ "$KAFKA_ZOOKEEPER_TLS_TYPE" = "PEM" ]] &&
                { [[ ! -f "${KAFKA_CERTS_DIR}/zookeeper.keystore.pem" ]] || [[ ! -f "${KAFKA_CERTS_DIR}/zookeeper.keystore.key" ]]; } &&
                { [[ ! -f "${KAFKA_MOUNTED_CONF_DIR}/certs/zookeeper.keystore.pem" ]] || [[ ! -f "${KAFKA_MOUNTED_CONF_DIR}/certs/zookeeper.keystore.key" ]]; }; then
                warn "In order to configure the mTLS for Zookeeper with PEM certs you must mount your zookeeper.keystore.pem cert and zookeeper.keystore.key key to the ${KAFKA_MOUNTED_CONF_DIR}/certs directory."
            fi
        elif [[ "${KAFKA_ZOOKEEPER_PROTOCOL}" =~ SASL ]]; then
            if [[ -z "$KAFKA_ZOOKEEPER_USER" ]] || [[ -z "$KAFKA_ZOOKEEPER_PASSWORD" ]]; then
                print_validation_error "In order to configure SASL authentication for Kafka, you must provide the SASL credentials. Set the environment variables KAFKA_ZOOKEEPER_USER and KAFKA_ZOOKEEPER_PASSWORD, to configure the credentials for SASL authentication with Zookeeper."
            fi
        elif ! is_boolean_yes "$ALLOW_PLAINTEXT_LISTENER"; then
            print_validation_error "The KAFKA_ZOOKEEPER_PROTOCOL environment variable does not configure a secure protocol. Set the environment variable ALLOW_PLAINTEXT_LISTENER=yes to allow the container to be started with a plaintext listener. This is only recommended for development."
        fi
    fi
    check_multi_value "KAFKA_TLS_TYPE" "JKS PEM"
    check_multi_value "KAFKA_ZOOKEEPER_TLS_TYPE" "JKS PEM"
    check_multi_value "KAFKA_TLS_CLIENT_AUTH" "none requested required"
    [[ "$error_code" -eq 0 ]] || return "$error_code"
}

########################
# Generate JAAS authentication file
# Globals:
#   KAFKA_*
# Arguments:
#   $1 - Authentication protocol to use for the internal listener
#   $2 - Authentication protocol to use for the client listener
# Returns:
#   None
#########################
kafka_generate_jaas_authentication_file() {
    local -r internal_protocol="${1:-}"
    local -r client_protocol="${2:-}"

    if [[ ! -f "${KAFKA_CONF_DIR}/kafka_jaas.conf" ]]; then
        info "Generating JAAS authentication file"

        read -r -a users <<<"$(tr ',;' ' ' <<<"${KAFKA_CLIENT_USERS:-}")"
        read -r -a passwords <<<"$(tr ',;' ' ' <<<"${KAFKA_CLIENT_PASSWORDS:-}")"

        if [[ "${client_protocol:-}" =~ SASL ]]; then
            if [[ "${KAFKA_CFG_SASL_ENABLED_MECHANISMS:-}" =~ PLAIN ]]; then
                cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
KafkaClient {
   org.apache.kafka.common.security.plain.PlainLoginModule required
EOF
            else
                cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
KafkaClient {
   org.apache.kafka.common.security.plain.ScramLoginModule required
EOF
            fi
            cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
   username="${users[0]:-}"
   password="${passwords[0]:-}";
   };
EOF
        fi
        if [[ "${client_protocol:-}" =~ SASL ]] && [[ "${internal_protocol:-}" =~ SASL ]]; then
            if [[ "${KAFKA_CFG_SASL_ENABLED_MECHANISMS:-}" =~ PLAIN ]] && [[ "${KAFKA_CFG_SASL_MECHANISM_INTER_BROKER_PROTOCOL:-}" =~ PLAIN ]]; then
                cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
KafkaServer {
   org.apache.kafka.common.security.plain.PlainLoginModule required
   username="${KAFKA_INTER_BROKER_USER:-}"
   password="${KAFKA_INTER_BROKER_PASSWORD:-}"
   user_${KAFKA_INTER_BROKER_USER:-}="${KAFKA_INTER_BROKER_PASSWORD:-}"
EOF
                for ((i = 0; i < ${#users[@]}; i++)); do
                    if [[ "$i" -eq "(( ${#users[@]} - 1 ))" ]]; then
                        cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
   user_${users[i]:-}="${passwords[i]:-}";
EOF
                    else
                        cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
   user_${users[i]:-}="${passwords[i]:-}"
EOF
                    fi
                done
                cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
   org.apache.kafka.common.security.scram.ScramLoginModule required;
   };
EOF
            else
                cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
KafkaServer {
   org.apache.kafka.common.security.scram.ScramLoginModule required
   username="${KAFKA_INTER_BROKER_USER:-}"
   password="${KAFKA_INTER_BROKER_PASSWORD:-}";
   };
EOF
            fi
        elif [[ "${client_protocol:-}" =~ SASL ]]; then
            cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
KafkaServer {
   org.apache.kafka.common.security.plain.PlainLoginModule required
EOF
            if [[ "${KAFKA_CFG_SASL_ENABLED_MECHANISMS:-}" =~ PLAIN ]]; then
                for ((i = 0; i < ${#users[@]}; i++)); do
                    if [[ "$i" -eq "(( ${#users[@]} - 1 ))" ]]; then
                        cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
   user_${users[i]:-}="${passwords[i]:-}";
EOF
                    else
                        cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
   user_${users[i]:-}="${passwords[i]:-}"
EOF
                    fi
                done
            fi
            cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
   org.apache.kafka.common.security.scram.ScramLoginModule required;
   };
EOF
        elif [[ "${internal_protocol:-}" =~ SASL ]]; then
            if [[ "${KAFKA_CFG_SASL_ENABLED_MECHANISMS:-}" =~ PLAIN ]] && [[ "${KAFKA_CFG_SASL_MECHANISM_INTER_BROKER_PROTOCOL:-}" =~ PLAIN ]]; then
                cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
KafkaServer {
   org.apache.kafka.common.security.plain.PlainLoginModule required
   username="${KAFKA_INTER_BROKER_USER:-}"
   password="${KAFKA_INTER_BROKER_PASSWORD:-}"
   user_${KAFKA_INTER_BROKER_USER:-}="${KAFKA_INTER_BROKER_PASSWORD:-}";
   org.apache.kafka.common.security.scram.ScramLoginModule required;
   };
EOF
            else
                cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
KafkaServer {
   org.apache.kafka.common.security.scram.ScramLoginModule required
   username="${KAFKA_INTER_BROKER_USER:-}"
   password="${KAFKA_INTER_BROKER_PASSWORD:-}";
   };
EOF
            fi
        fi
        if [[ "${KAFKA_ZOOKEEPER_PROTOCOL}" =~ SASL ]] && [[ -n "$KAFKA_ZOOKEEPER_USER" ]] && [[ -n "$KAFKA_ZOOKEEPER_PASSWORD" ]]; then
            cat >>"${KAFKA_CONF_DIR}/kafka_jaas.conf" <<EOF
Client {
   org.apache.kafka.common.security.plain.PlainLoginModule required
   username="${KAFKA_ZOOKEEPER_USER:-}"
   password="${KAFKA_ZOOKEEPER_PASSWORD:-}";
   };
EOF
        fi
    else
        info "Custom JAAS authentication file detected. Skipping generation."
        warn "The following environment variables will be ignored: KAFKA_CLIENT_USERS, KAFKA_CLIENT_PASSWORDS, KAFKA_INTER_BROKER_USER, KAFKA_INTER_BROKER_PASSWORD, KAFKA_ZOOKEEPER_USER and KAFKA_ZOOKEEPER_PASSWORD"
    fi
}

########################
# Create users in zookeper when using SASL_SCRAM
# Globals:
#   KAFKA_*
# Arguments:
#   None
# Returns:
#   None
#########################
kafka_create_sasl_scram_zookeeper_users() {
    export KAFKA_OPTS="-Djava.security.auth.login.config=${KAFKA_CONF_DIR}/kafka_jaas.conf"
    info "Creating users in Zookeeper"
    read -r -a users <<<"$(tr ',;' ' ' <<<"${KAFKA_CLIENT_USERS}")"
    read -r -a passwords <<<"$(tr ',;' ' ' <<<"${KAFKA_CLIENT_PASSWORDS}")"
    if [[ "${KAFKA_CFG_SASL_MECHANISM_INTER_BROKER_PROTOCOL:-}" =~ SCRAM-SHA ]]; then
        users+=("${KAFKA_INTER_BROKER_USER}")
        passwords+=("${KAFKA_INTER_BROKER_PASSWORD}")
    fi
    for ((i = 0; i < ${#users[@]}; i++)); do
        debug "Creating user ${users[i]} in zookeeper"
        # Ref: https://docs.confluent.io/current/kafka/authentication_sasl/authentication_sasl_scram.html#sasl-scram-overview
        if [[ "${KAFKA_ZOOKEEPER_PROTOCOL:-}" =~ SSL ]]; then
            ZOOKEEPER_SSL_CONFIG=$(zookeeper_get_tls_config)
            export KAFKA_OPTS="$KAFKA_OPTS $ZOOKEEPER_SSL_CONFIG"
        fi
        debug_execute kafka-configs.sh --zookeeper "$KAFKA_CFG_ZOOKEEPER_CONNECT" --alter --add-config "SCRAM-SHA-256=[iterations=8192,password=${passwords[i]}],SCRAM-SHA-512=[password=${passwords[i]}]" --entity-type users --entity-name "${users[i]}"
    done
}

########################
# Configure Kafka SSL settings
# Globals:
#   KAFKA_*
# Arguments:
#   None
# Returns:
#   None
#########################
SSL_CONFIGURED=false
kafka_configure_ssl() {
    [[ "$SSL_CONFIGURED" = true ]] && return 0
    # Configures both Kafka server and producers/consumers
    configure_both() {
        kafka_server_conf_set "${1:?missing key}" "${2:?missing value}"
        kafka_producer_consumer_conf_set "${1:?missing key}" "${2:?missing value}"
    }
    configure_both ssl.keystore.type "${KAFKA_TLS_TYPE}"
    configure_both ssl.truststore.type "${KAFKA_TLS_TYPE}"
    local -r kafka_truststore_location="${KAFKA_CERTS_DIR}/$(basename "${KAFKA_TLS_TRUSTSTORE_FILE}")"
    ! is_empty_value "$KAFKA_CERTIFICATE_PASSWORD" && configure_both ssl.key.password "$KAFKA_CERTIFICATE_PASSWORD"
    if [[ "$KAFKA_TLS_TYPE" = "PEM" ]]; then
        file_to_multiline_property() {
            awk 'NR > 1{print line" \\"}{line=$0;}END{print $0" "}' <"${1:?missing file}"
        }
        configure_both ssl.keystore.key "$(file_to_multiline_property "${KAFKA_CERTS_DIR}/kafka.keystore.key")"
        configure_both ssl.keystore.certificate.chain "$(file_to_multiline_property "${KAFKA_CERTS_DIR}/kafka.keystore.pem")"
        configure_both ssl.truststore.certificates "$(file_to_multiline_property "${kafka_truststore_location}")"
    elif [[ "$KAFKA_TLS_TYPE" = "JKS" ]]; then
        configure_both ssl.keystore.location "$KAFKA_CERTS_DIR"/kafka.keystore.jks
        configure_both ssl.truststore.location "$kafka_truststore_location"
        ! is_empty_value "$KAFKA_CERTIFICATE_PASSWORD" && configure_both ssl.keystore.password "$KAFKA_CERTIFICATE_PASSWORD"
        ! is_empty_value "$KAFKA_CERTIFICATE_PASSWORD" && configure_both ssl.truststore.password "$KAFKA_CERTIFICATE_PASSWORD"
    fi
    SSL_CONFIGURED=true # prevents configuring SSL more than once
}

########################
# Configure Kafka for inter-broker communications
# Globals:
#   None
# Arguments:
#   $1 - Authentication protocol to use for the internal listener
# Returns:
#   None
#########################
kafka_configure_internal_communications() {
    local -r protocol="${1:?missing environment variable protocol}"
    local -r allowed_protocols=("PLAINTEXT" "SASL_PLAINTEXT" "SASL_SSL" "SSL")
    info "Configuring Kafka for inter-broker communications with ${protocol} authentication."

    if [[ "${allowed_protocols[*]}" =~ $protocol ]]; then
        kafka_server_conf_set security.inter.broker.protocol "$protocol"
        if [[ "$protocol" = "PLAINTEXT" ]]; then
            warn "Inter-broker communications are configured as PLAINTEXT. This is not safe for production environments."
        fi
        if [[ "$protocol" = "SASL_PLAINTEXT" ]] || [[ "$protocol" = "SASL_SSL" ]]; then
            # IMPORTANT: Do not confuse SASL/PLAIN with PLAINTEXT
            # For more information, see: https://docs.confluent.io/current/kafka/authentication_sasl/authentication_sasl_plain.html#sasl-plain-overview)
            if [[ -n "$KAFKA_CFG_SASL_MECHANISM_INTER_BROKER_PROTOCOL" ]]; then
                kafka_server_conf_set sasl.mechanism.inter.broker.protocol "$KAFKA_CFG_SASL_MECHANISM_INTER_BROKER_PROTOCOL"
            else
                error "When using SASL for inter broker comunication the mechanism should be provided at KAFKA_CFG_SASL_MECHANISM_INTER_BROKER_PROTOCOL"
                exit 1
            fi
        fi
        if [[ "$protocol" = "SASL_SSL" ]] || [[ "$protocol" = "SSL" ]]; then
            kafka_configure_ssl
            # We need to enable 2 way authentication on SASL_SSL so brokers authenticate each other.
            # It won't affect client communications unless the SSL protocol is for them.
            kafka_server_conf_set ssl.client.auth "$KAFKA_TLS_CLIENT_AUTH"
        fi
    else
        error "Authentication protocol ${protocol} is not supported!"
        exit 1
    fi
}

########################
# Configure Kafka for client communications
# Globals:
#   None
# Arguments:
#   $1 - Authentication protocol to use for the client listener
# Returns:
#   None
#########################
kafka_configure_client_communications() {
    local -r protocol="${1:?missing environment variable protocol}"
    local -r allowed_protocols=("PLAINTEXT" "SASL_PLAINTEXT" "SASL_SSL" "SSL")
    info "Configuring Kafka for client communications with ${protocol} authentication."

    if [[ "${allowed_protocols[*]}" =~ ${protocol} ]]; then
        kafka_server_conf_set security.inter.broker.protocol "$protocol"
        if [[ "$protocol" = "PLAINTEXT" ]]; then
            warn "Client communications are configured using PLAINTEXT listeners. For safety reasons, do not use this in a production environment."
        fi
        if [[ "$protocol" = "SASL_PLAINTEXT" ]] || [[ "$protocol" = "SASL_SSL" ]]; then
            # The below lines would need to be updated to support other SASL implementations (i.e. GSSAPI)
            # IMPORTANT: Do not confuse SASL/PLAIN with PLAINTEXT
            # For more information, see: https://docs.confluent.io/current/kafka/authentication_sasl/authentication_sasl_plain.html#sasl-plain-overview)
            kafka_server_conf_set sasl.mechanism.inter.broker.protocol "$KAFKA_CFG_SASL_MECHANISM_INTER_BROKER_PROTOCOL"
        fi
        if [[ "$protocol" = "SASL_SSL" ]] || [[ "$protocol" = "SSL" ]]; then
            kafka_configure_ssl
        fi
        if [[ "$protocol" = "SSL" ]]; then
            kafka_server_conf_set ssl.client.auth "$KAFKA_TLS_CLIENT_AUTH"
        fi
    else
        error "Authentication protocol ${protocol} is not supported!"
        exit 1
    fi
}

########################
# Configure Kafka for external-client communications
# Globals:
#   None
# Arguments:
#   $1 - Authentication protocol to use for the external-client listener
# Returns:
#   None
#########################
kafka_configure_external_client_communications() {
    local -r protocol="${1:?missing environment variable protocol}"
    local -r allowed_protocols=("PLAINTEXT" "SASL_PLAINTEXT" "SASL_SSL" "SSL")
    info "Configuring Kafka for external client communications with ${protocol} authentication."

    if [[ "${allowed_protocols[*]}" =~ ${protocol} ]]; then
        if [[ "$protocol" = "PLAINTEXT" ]]; then
            warn "External client communications are configured using PLAINTEXT listeners. For safety reasons, do not use this in a production environment."
        fi
        if [[ "$protocol" = "SASL_SSL" ]] || [[ "$protocol" = "SSL" ]]; then
            kafka_configure_ssl
        fi
        if [[ "$protocol" = "SSL" ]]; then
            kafka_server_conf_set ssl.client.auth "$KAFKA_TLS_CLIENT_AUTH"
        fi
    else
        error "Authentication protocol ${protocol} is not supported!"
        exit 1
    fi
}

########################
# Get Zookeeper TLS settings
# Globals:
#   KAFKA_ZOOKEEPER_TLS_*
# Arguments:
#   None
# Returns:
#   String
#########################
zookeeper_get_tls_config() {
    # Note that ZooKeeper does not support a key password different from the keystore password,
    # so be sure to set the key password in the keystore to be identical to the keystore password;
    # otherwise the connection attempt to Zookeeper will fail.
    local keystore_location=""
    local -r kafka_zk_truststore_location="${KAFKA_CERTS_DIR}/$(basename "${KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_FILE}")"

    if [[ "$KAFKA_ZOOKEEPER_TLS_TYPE" = "JKS" ]] && [[ -f "$KAFKA_CERTS_DIR"/zookeeper.keystore.jks ]]; then
        keystore_location="${KAFKA_CERTS_DIR}/zookeeper.keystore.jks"
    elif [[ "$KAFKA_ZOOKEEPER_TLS_TYPE" = "PEM" ]] && [[ -f "$KAFKA_CERTS_DIR"/zookeeper.keystore.pem ]] && [[ -f "$KAFKA_CERTS_DIR"/zookeeper.keystore.key ]]; then
        # Concatenating private key into public certificate file
        # This is needed to load keystore from location using PEM
        cat "$KAFKA_CERTS_DIR"/zookeeper.keystore.key >>"$KAFKA_CERTS_DIR"/zookeeper.keystore.pem
        keystore_location="${KAFKA_CERTS_DIR}/zookeeper.keystore.pem"
    fi

    echo "-Dzookeeper.clientCnxnSocket=org.apache.zookeeper.ClientCnxnSocketNetty \
          -Dzookeeper.client.secure=true \
          -Dzookeeper.ssl.keyStore.location=${keystore_location} \
          -Dzookeeper.ssl.keyStore.password=${KAFKA_ZOOKEEPER_TLS_KEYSTORE_PASSWORD} \
          -Dzookeeper.ssl.trustStore.location=${kafka_zk_truststore_location} \
          -Dzookeeper.ssl.trustStore.password=${KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_PASSWORD} \
          -Dzookeeper.ssl.hostnameVerification=${KAFKA_ZOOKEEPER_TLS_VERIFY_HOSTNAME}"
}

########################
# Configure Kafka configuration files from environment variables
# Globals:
#   KAFKA_*
# Arguments:
#   None
# Returns:
#   None
#########################
kafka_configure_from_environment_variables() {
    # List of special cases to apply to the variables
    local -r exception_regexps=(
        "s/sasl.ssl/sasl_ssl/g"
        "s/sasl.plaintext/sasl_plaintext/g"
    )
    # Map environment variables to config properties
    for var in "${!KAFKA_CFG_@}"; do
        key="$(echo "$var" | sed -e 's/^KAFKA_CFG_//g' -e 's/_/\./g' | tr '[:upper:]' '[:lower:]')"

        # Exception for the camel case in this environment variable
        [[ "$var" == "KAFKA_CFG_ZOOKEEPER_CLIENTCNXNSOCKET" ]] && key="zookeeper.clientCnxnSocket"

        # Apply exception regexps
        for regex in "${exception_regexps[@]}"; do
            key="$(echo "$key" | sed "$regex")"
        done

        value="${!var}"
        kafka_server_conf_set "$key" "$value"
    done
}

########################
# Configure Kafka configuration files to set up message sizes
# Globals:
#   KAFKA_*
# Arguments:
#   None
# Returns:
#   None
#########################
kafka_configure_producer_consumer_message_sizes() {
    if [[ -n "$KAFKA_CFG_MAX_REQUEST_SIZE" ]]; then
        kafka_common_conf_set "$KAFKA_CONF_DIR/producer.properties" max.request.size "$KAFKA_CFG_MAX_REQUEST_SIZE"
    fi
    if [[ -n "$KAFKA_CFG_MAX_PARTITION_FETCH_BYTES" ]]; then
        kafka_common_conf_set "$KAFKA_CONF_DIR/consumer.properties" max.partition.fetch.bytes "$KAFKA_CFG_MAX_PARTITION_FETCH_BYTES"
    fi
}

########################
# Initialize KRaft
# Globals:
#   KAFKA_*
# Arguments:
#   None
# Returns:
#   None
#########################
kraft_initialize() {
    info "Initializing KRaft..."

    if [[ -z "$KAFKA_KRAFT_CLUSTER_ID" ]]; then
        warn "KAFKA_KRAFT_CLUSTER_ID not set - If using multiple nodes then you must use the same Cluster ID for each one"
        KAFKA_KRAFT_CLUSTER_ID="$("${KAFKA_HOME}/bin/kafka-storage.sh" random-uuid)"
        info "Generated Kafka cluster ID '${KAFKA_KRAFT_CLUSTER_ID}'"
    fi

    info "Formatting storage directories to add metadata..."
    debug_execute "$KAFKA_HOME/bin/kafka-storage.sh" format --config "$KAFKA_CONF_FILE" --cluster-id "$KAFKA_KRAFT_CLUSTER_ID" --ignore-formatted
}

########################
# Initialize Kafka
# Globals:
#   KAFKA_*
# Arguments:
#   None
# Returns:
#   None
#########################
kafka_initialize() {
    info "Initializing Kafka..."
    # DEPRECATED. Copy files in old conf directory to maintain compatibility with Helm chart.
    if ! is_dir_empty "$KAFKA_BASE_DIR"/conf; then
        warn "Detected files mounted to $KAFKA_BASE_DIR/conf. This is deprecated and files should be mounted to $KAFKA_MOUNTED_CONF_DIR."
        cp -Lr "$KAFKA_BASE_DIR"/conf/* "$KAFKA_CONF_DIR"
    fi
    # Check for mounted configuration files
    if ! is_dir_empty "$KAFKA_MOUNTED_CONF_DIR"; then
        cp -Lr "$KAFKA_MOUNTED_CONF_DIR"/* "$KAFKA_CONF_DIR"
    fi
    # Copy truststore to cert directory
    for cert_var in KAFKA_TLS_TRUSTSTORE_FILE KAFKA_ZOOKEEPER_TLS_TRUSTSTORE_FILE; do
        # Only copy if the file exists and it is in a different location than KAFKA_CERTS_DIR (to avoid copying to the same location)
        if [[ -f "${!cert_var}" ]] && ! [[ "${!cert_var}" =~ $KAFKA_CERTS_DIR ]]; then
            info "Copying truststore ${!cert_var} to ${KAFKA_CERTS_DIR}"
            cp -L "${!cert_var}" "$KAFKA_CERTS_DIR"
        fi
    done

    # DEPRECATED. Check for server.properties file in old conf directory to maintain compatibility with Helm chart.
    if [[ ! -f "$KAFKA_BASE_DIR"/conf/server.properties ]] && [[ ! -f "$KAFKA_MOUNTED_CONF_DIR"/server.properties ]]; then
        info "No injected configuration files found, creating default config files"
        kafka_server_conf_set log.dirs "$KAFKA_DATA_DIR"
        kafka_configure_from_environment_variables
        # When setting up a Kafka cluster with N brokers, we have several listeners:
        # - INTERNAL: used for inter-broker communications
        # - CLIENT: used for communications with consumers/producers within the same network
        # - (optional) EXTERNAL: used for communications with consumers/producers on different networks
        local internal_protocol
        local client_protocol
        local external_client_protocol
        if [[ ${KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP:-} =~ INTERNAL:([a-zA-Z_]*) ]]; then
            internal_protocol="${BASH_REMATCH[1]}"
            kafka_configure_internal_communications "$internal_protocol"
        fi
        if [[ ${KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP:-} =~ CLIENT:([a-zA-Z_]*) ]]; then
            client_protocol="${BASH_REMATCH[1]}"
            kafka_configure_client_communications "$client_protocol"
        fi
        if [[ ${KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP:-} =~ EXTERNAL:([a-zA-Z_]*) ]]; then
            external_client_protocol="${BASH_REMATCH[1]}"
            kafka_configure_external_client_communications "$external_client_protocol"
        fi

        if [[ "${internal_protocol:-}" =~ "SASL" || "${client_protocol:-}" =~ "SASL" || "${external_client_protocol:-}" =~ "SASL" ]] || [[ "${KAFKA_ZOOKEEPER_PROTOCOL}" =~ SASL ]]; then
            if [[ -n "$KAFKA_CFG_SASL_ENABLED_MECHANISMS" ]]; then
                kafka_server_conf_set sasl.enabled.mechanisms "$KAFKA_CFG_SASL_ENABLED_MECHANISMS"
                kafka_generate_jaas_authentication_file "${internal_protocol:-}" "${client_protocol:-}"
                [[ "$KAFKA_CFG_SASL_ENABLED_MECHANISMS" =~ "SCRAM" ]] && kafka_create_sasl_scram_zookeeper_users
            else
                print_validation_error "Specified SASL protocol but no SASL mechanisms provided in KAFKA_CFG_SASL_ENABLED_MECHANISMS"
            fi
        fi
        # Remove security.inter.broker.protocol if KAFKA_CFG_INTER_BROKER_LISTENER_NAME is configured
        if [[ -n "${KAFKA_CFG_INTER_BROKER_LISTENER_NAME:-}" ]]; then
            remove_in_file "$KAFKA_CONF_FILE" "security.inter.broker.protocol" false
        fi
        kafka_configure_producer_consumer_message_sizes
    fi
    true
}

########################
# Run custom initialization scripts
# Globals:
#   KAFKA_*
# Arguments:
#   None
# Returns:
#   None
#########################
kafka_custom_init_scripts() {
    if [[ -n $(find "${KAFKA_INITSCRIPTS_DIR}/" -type f -regex ".*\.\(sh\)") ]] && [[ ! -f "${KAFKA_VOLUME_DIR}/.user_scripts_initialized" ]]; then
        info "Loading user's custom files from $KAFKA_INITSCRIPTS_DIR"
        for f in /docker-entrypoint-initdb.d/*; do
            debug "Executing $f"
            case "$f" in
            *.sh)
                if [[ -x "$f" ]]; then
                    if ! "$f"; then
                        error "Failed executing $f"
                        return 1
                    fi
                else
                    warn "Sourcing $f as it is not executable by the current user, any error may cause initialization to fail"
                    . "$f"
                fi
                ;;
            *)
                warn "Skipping $f, supported formats are: .sh"
                ;;
            esac
        done
        touch "$KAFKA_VOLUME_DIR"/.user_scripts_initialized
    fi
}

########################
# Check if Kafka is running
# Globals:
#   KAFKA_PID_FILE
# Arguments:
#   None
# Returns:
#   Whether Kafka is running
########################
is_kafka_running() {
    local pid
    pid="$(get_pid_from_file "$KAFKA_PID_FILE")"
    if [[ -n "$pid" ]]; then
        is_service_running "$pid"
    else
        false
    fi
}

########################
# Check if Kafka is running
# Globals:
#   KAFKA_PID_FILE
# Arguments:
#   None
# Returns:
#   Whether Kafka is not running
########################
is_kafka_not_running() {
    ! is_kafka_running
}

########################
# Stop Kafka
# Globals:
#   KAFKA_PID_FILE
# Arguments:
#   None
# Returns:
#   None
#########################
kafka_stop() {
    ! is_kafka_running && return
    stop_service_using_pid "$KAFKA_PID_FILE" TERM
}
