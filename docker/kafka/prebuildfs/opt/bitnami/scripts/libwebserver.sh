#!/bin/bash
#
# Bitnami web server handler library

# shellcheck disable=SC1090,SC1091

# Load generic libraries
. /opt/bitnami/scripts/liblog.sh

########################
# Execute a command (or list of commands) with the web server environment and library loaded
# Globals:
#   *
# Arguments:
#   None
# Returns:
#   None
#########################
web_server_execute() {
    local -r web_server="${1:?missing web server}"
    shift
    # Run program in sub-shell to avoid web server environment getting loaded when not necessary
    (
        . "/opt/bitnami/scripts/lib${web_server}.sh"
        . "/opt/bitnami/scripts/${web_server}-env.sh"
        "$@"
    )
}

########################
# Prints the list of enabled web servers
# Globals:
#   None
# Arguments:
#   None
# Returns:
#   None
#########################
web_server_list() {
    local -r -a supported_web_servers=(apache nginx)
    local -a existing_web_servers=()
    for web_server in "${supported_web_servers[@]}"; do
        [[ -f "/opt/bitnami/scripts/${web_server}-env.sh" ]] && existing_web_servers+=("$web_server")
    done
    echo "${existing_web_servers[@]:-}"
}

########################
# Prints the currently-enabled web server type (only one, in order of preference)
# Globals:
#   None
# Arguments:
#   None
# Returns:
#   None
#########################
web_server_type() {
    local -a web_servers
    read -r -a web_servers <<< "$(web_server_list)"
    echo "${web_servers[0]:-}"
}

########################
# Validate that a supported web server is configured
# Globals:
#   None
# Arguments:
#   None
# Returns:
#   None
#########################
web_server_validate() {
    local error_code=0
    local supported_web_servers=("apache" "nginx")

    # Auxiliary functions
    print_validation_error() {
        error "$1"
        error_code=1
    }

    if [[ -z "$(web_server_type)" || ! " ${supported_web_servers[*]} " == *" $(web_server_type) "* ]]; then
        print_validation_error "Could not detect any supported web servers. It must be one of: ${supported_web_servers[*]}"
    elif ! web_server_execute "$(web_server_type)" type -t "is_$(web_server_type)_running" >/dev/null; then
        print_validation_error "Could not load the $(web_server_type) web server library from /opt/bitnami/scripts. Check that it exists and is readable."
    fi

    return "$error_code"
}

########################
# Check whether the web server is running
# Globals:
#   *
# Arguments:
#   None
# Returns:
#   true if the web server is running, false otherwise
#########################
is_web_server_running() {
    "is_$(web_server_type)_running"
}

########################
# Start web server
# Globals:
#   *
# Arguments:
#   None
# Returns:
#   None
#########################
web_server_start() {
    info "Starting $(web_server_type) in background"
    "${BITNAMI_ROOT_DIR}/scripts/$(web_server_type)/start.sh"
}

########################
# Stop web server
# Globals:
#   *
# Arguments:
#   None
# Returns:
#   None
#########################
web_server_stop() {
    info "Stopping $(web_server_type)"
    "${BITNAMI_ROOT_DIR}/scripts/$(web_server_type)/stop.sh"
}

########################
# Restart web server
# Globals:
#   *
# Arguments:
#   None
# Returns:
#   None
#########################
web_server_restart() {
    info "Restarting $(web_server_type)"
    "${BITNAMI_ROOT_DIR}/scripts/$(web_server_type)/restart.sh"
}

########################
# Reload web server
# Globals:
#   *
# Arguments:
#   None
# Returns:
#   None
#########################
web_server_reload() {
    "${BITNAMI_ROOT_DIR}/scripts/$(web_server_type)/reload.sh"
}

########################
# Ensure a web server application configuration exists (i.e. Apache virtual host format or NGINX server block)
# It serves as a wrapper for the specific web server function
# Globals:
#   *
# Arguments:
#   $1 - App name
# Flags:
#   --type - Application type, which has an effect on which configuration template to use
#   --hosts - Host listen addresses
#   --server-name - Server name
#   --server-aliases - Server aliases
#   --allow-remote-connections - Whether to allow remote connections or to require local connections
#   --disable - Whether to render server configurations with a .disabled prefix
#   --disable-http - Whether to render the app's HTTP server configuration with a .disabled prefix
#   --disable-https - Whether to render the app's HTTPS server configuration with a .disabled prefix
#   --http-port - HTTP port number
#   --https-port - HTTPS port number
#   --document-root - Path to document root directory
# Apache-specific flags:
#   --apache-additional-configuration - Additional vhost configuration (no default)
#   --apache-additional-http-configuration - Additional HTTP vhost configuration (no default)
#   --apache-additional-https-configuration - Additional HTTPS vhost configuration (no default)
#   --apache-before-vhost-configuration - Configuration to add before the <VirtualHost> directive (no default)
#   --apache-allow-override - Whether to allow .htaccess files (only allowed when --move-htaccess is set to 'no' and type is not defined)
#   --apache-extra-directory-configuration - Extra configuration for the document root directory
#   --apache-proxy-address - Address where to proxy requests
#   --apache-proxy-configuration - Extra configuration for the proxy
#   --apache-proxy-http-configuration - Extra configuration for the proxy HTTP vhost
#   --apache-proxy-https-configuration - Extra configuration for the proxy HTTPS vhost
#   --apache-move-htaccess - Move .htaccess files to a common place so they can be loaded during Apache startup (only allowed when type is not defined)
# NGINX-specific flags:
#   --nginx-additional-configuration - Additional server block configuration (no default)
#   --nginx-external-configuration - Configuration external to server block (no default)
# Returns:
#   true if the configuration was enabled, false otherwise
########################
ensure_web_server_app_configuration_exists() {
    local app="${1:?missing app}"
    shift
    local -a apache_args nginx_args web_servers args_var
    apache_args=("$app")
    nginx_args=("$app")
    # Validate arguments
    while [[ "$#" -gt 0 ]]; do
        case "$1" in
            # Common flags
            --disable \
            | --disable-http \
            | --disable-https \
            )
                apache_args+=("$1")
                nginx_args+=("$1")
                ;;
            --hosts \
            | --server-name \
            | --server-aliases \
            | --type \
            | --allow-remote-connections \
            | --http-port \
            | --https-port \
            | --document-root \
            )
                apache_args+=("$1" "${2:?missing value}")
                nginx_args+=("$1" "${2:?missing value}")
                shift
                ;;

            # Specific Apache flags
            --apache-additional-configuration \
            | --apache-additional-http-configuration \
            | --apache-additional-https-configuration \
            | --apache-before-vhost-configuration \
            | --apache-allow-override \
            | --apache-extra-directory-configuration \
            | --apache-proxy-address \
            | --apache-proxy-configuration \
            | --apache-proxy-http-configuration \
            | --apache-proxy-https-configuration \
            | --apache-move-htaccess \
            )
                apache_args+=("${1//apache-/}" "${2:?missing value}")
                shift
                ;;

            # Specific NGINX flags
            --nginx-additional-configuration \
            | --nginx-external-configuration)
                nginx_args+=("${1//nginx-/}" "${2:?missing value}")
                shift
                ;;

            *)
                echo "Invalid command line flag $1" >&2
                return 1
                ;;
        esac
        shift
    done
    read -r -a web_servers <<< "$(web_server_list)"
    for web_server in "${web_servers[@]}"; do
        args_var="${web_server}_args[@]"
        web_server_execute "$web_server" "ensure_${web_server}_app_configuration_exists" "${!args_var}"
    done
}

########################
# Ensure a web server application configuration does not exist anymore (i.e. Apache virtual host format or NGINX server block)
# It serves as a wrapper for the specific web server function
# Globals:
#   *
# Arguments:
#   $1 - App name
# Returns:
#   true if the configuration was disabled, false otherwise
########################
ensure_web_server_app_configuration_not_exists() {
    local app="${1:?missing app}"
    local -a web_servers
    read -r -a web_servers <<< "$(web_server_list)"
    for web_server in "${web_servers[@]}"; do
        web_server_execute "$web_server" "ensure_${web_server}_app_configuration_not_exists" "$app"
    done
}

########################
# Ensure the web server loads the configuration for an application in a URL prefix
# It serves as a wrapper for the specific web server function
# Globals:
#   *
# Arguments:
#   $1 - App name
# Flags:
#   --allow-remote-connections - Whether to allow remote connections or to require local connections
#   --document-root - Path to document root directory
#   --prefix - URL prefix from where it will be accessible (i.e. /myapp)
#   --type - Application type, which has an effect on what configuration template will be used
# Apache-specific flags:
#   --apache-additional-configuration - Additional vhost configuration (no default)
#   --apache-allow-override - Whether to allow .htaccess files (only allowed when --move-htaccess is set to 'no')
#   --apache-extra-directory-configuration - Extra configuration for the document root directory
#   --apache-move-htaccess - Move .htaccess files to a common place so they can be loaded during Apache startup
# NGINX-specific flags:
#   --nginx-additional-configuration - Additional server block configuration (no default)
# Returns:
#   true if the configuration was enabled, false otherwise
########################
ensure_web_server_prefix_configuration_exists() {
    local app="${1:?missing app}"
    shift
    local -a apache_args nginx_args web_servers args_var
    apache_args=("$app")
    nginx_args=("$app")
    # Validate arguments
    while [[ "$#" -gt 0 ]]; do
        case "$1" in
            # Common flags
            --allow-remote-connections \
            | --document-root \
            | --prefix \
            | --type \
            )
                apache_args+=("$1" "${2:?missing value}")
                nginx_args+=("$1" "${2:?missing value}")
                shift
                ;;

            # Specific Apache flags
            --apache-additional-configuration \
            | --apache-allow-override \
            | --apache-extra-directory-configuration \
            | --apache-move-htaccess \
            )
                apache_args+=("${1//apache-/}" "$2")
                shift
                ;;

            # Specific NGINX flags
            --nginx-additional-configuration)
                nginx_args+=("${1//nginx-/}" "$2")
                shift
                ;;

            *)
                echo "Invalid command line flag $1" >&2
                return 1
                ;;
        esac
        shift
    done
    read -r -a web_servers <<< "$(web_server_list)"
    for web_server in "${web_servers[@]}"; do
        args_var="${web_server}_args[@]"
        web_server_execute "$web_server" "ensure_${web_server}_prefix_configuration_exists" "${!args_var}"
    done
}

########################
# Ensure a web server application configuration is updated with the runtime configuration (i.e. ports)
# It serves as a wrapper for the specific web server function
# Globals:
#   *
# Arguments:
#   $1 - App name
# Flags:
#   --hosts - Host listen addresses
#   --server-name - Server name
#   --server-aliases - Server aliases
#   --enable-http - Enable HTTP app configuration (if not enabled already)
#   --enable-https - Enable HTTPS app configuration (if not enabled already)
#   --disable-http - Disable HTTP app configuration (if not disabled already)
#   --disable-https - Disable HTTPS app configuration (if not disabled already)
#   --http-port - HTTP port number
#   --https-port - HTTPS port number
# Returns:
#   true if the configuration was updated, false otherwise
########################
web_server_update_app_configuration() {
    local app="${1:?missing app}"
    shift
    local -a args web_servers
    args=("$app")
    # Validate arguments
    while [[ "$#" -gt 0 ]]; do
        case "$1" in
            # Common flags
            --enable-http \
            | --enable-https \
            | --disable-http \
            | --disable-https \
            )
                args+=("$1")
                ;;
            --hosts \
            | --server-name \
            | --server-aliases \
            | --http-port \
            | --https-port \
            )
                args+=("$1" "${2:?missing value}")
                shift
                ;;

            *)
                echo "Invalid command line flag $1" >&2
                return 1
                ;;
        esac
        shift
    done
    read -r -a web_servers <<< "$(web_server_list)"
    for web_server in "${web_servers[@]}"; do
        web_server_execute "$web_server" "${web_server}_update_app_configuration" "${args[@]}"
    done
}

########################
# Enable loading page, which shows users that the initialization process is not yet completed
# Globals:
#   *
# Arguments:
#   None
# Returns:
#   None
#########################
web_server_enable_loading_page() {
    ensure_web_server_app_configuration_exists "__loading" --hosts "_default_" \
        --apache-additional-configuration "
# Show a HTTP 503 Service Unavailable page by default
RedirectMatch 503 ^/$
# Show index.html if server is answering with 404 Not Found or 503 Service Unavailable status codes
ErrorDocument 404 /index.html
ErrorDocument 503 /index.html" \
        --nginx-additional-configuration "
# Show a HTTP 503 Service Unavailable page by default
location / {
  return 503;
}
# Show index.html if server is answering with 404 Not Found or 503 Service Unavailable status codes
error_page 404 @installing;
error_page 503 @installing;
location @installing {
  rewrite ^(.*)$ /index.html break;
}"
    web_server_reload
}

########################
# Enable loading page, which shows users that the initialization process is not yet completed
# Globals:
#   *
# Arguments:
#   None
# Returns:
#   None
#########################
web_server_disable_install_page() {
    ensure_web_server_app_configuration_not_exists "__loading"
    web_server_reload
}
