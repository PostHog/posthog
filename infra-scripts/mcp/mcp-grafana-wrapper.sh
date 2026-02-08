#!/usr/bin/env bash
# Wrapper script for mcp-grafana that uses kubectl port-forward to bypass ALB Cognito auth
#
# PostHog's Grafana instances require Cognito OAuth at the ALB level, which doesn't
# support Bearer token authentication. This script creates a port-forward to access
# Grafana directly within the K8s cluster, enabling the MCP server to authenticate
# with a service account token.
#
# Supports switching between prod-us, prod-eu, and dev regions via ~/.grafana-region file.
# Use `grafana-region us`, `grafana-region eu`, or `grafana-region dev` to switch,
# then restart your MCP client.
#
# Prerequisites:
#   - kubectl configured with access to PostHog K8s clusters
#   - AWS SSO session active (`aws sso login`)
#   - mcp-grafana binary installed (go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest)
#   - Grafana service account token stored in macOS Keychain (see grafana-token script)

set -euo pipefail

# Region configuration
REGION_FILE="$HOME/.grafana-region"
DEFAULT_REGION="us"

# Runtime directory for PID files (user-private, not world-writable /tmp)
RUNTIME_DIR="$HOME/.local/run"
mkdir -p "$RUNTIME_DIR" && chmod 700 "$RUNTIME_DIR"

# Read current region (default to us if file missing or empty)
if [ -f "$REGION_FILE" ] && [ -s "$REGION_FILE" ]; then
    CURRENT_REGION=$(head -n1 "$REGION_FILE" | tr -cd '[:alnum:]')
else
    CURRENT_REGION="$DEFAULT_REGION"
fi

# Validate region
if [[ "$CURRENT_REGION" != "us" && "$CURRENT_REGION" != "eu" && "$CURRENT_REGION" != "dev" ]]; then
    echo "Error: Invalid region '$CURRENT_REGION' in $REGION_FILE. Must be 'us', 'eu', or 'dev'." >&2
    exit 1
fi

# Look up kubectl context dynamically from ~/.kube/config by matching cluster name pattern
# This avoids hardcoding AWS account IDs and cluster ARNs in the script
get_k8s_context() {
    local pattern
    case "$1" in
        # us matches posthog-prod but not posthog-prod-eu
        us)  pattern='posthog-prod$' ;;
        eu)  pattern='posthog-prod-eu' ;;
        dev) pattern='posthog-dev' ;;
        *)   return 1 ;;
    esac
    kubectl config get-contexts -o name 2>/dev/null | grep -E "$pattern" | head -1
}

# Region-specific configuration
case "$CURRENT_REGION" in
    us)
        LOCAL_PORT=13000
        KEYCHAIN_SERVICE="grafana-service-account-token-us"
        PID_FILE="$RUNTIME_DIR/grafana-port-forward-us.pid"
        ;;
    eu)
        LOCAL_PORT=13001
        KEYCHAIN_SERVICE="grafana-service-account-token-eu"
        PID_FILE="$RUNTIME_DIR/grafana-port-forward-eu.pid"
        ;;
    dev)
        LOCAL_PORT=13002
        KEYCHAIN_SERVICE="grafana-service-account-token-dev"
        PID_FILE="$RUNTIME_DIR/grafana-port-forward-dev.pid"
        ;;
esac

# Look up the K8s context dynamically
K8S_CONTEXT=$(get_k8s_context "$CURRENT_REGION")
if [ -z "$K8S_CONTEXT" ]; then
    echo "Error: No kubectl context found for region '$CURRENT_REGION'" >&2
    echo "You may need to run: aws eks update-kubeconfig --name <cluster-name> --profile <profile>" >&2
    echo "Available contexts: $(kubectl config get-contexts -o name 2>/dev/null | tr '\n' ' ')" >&2
    exit 1
fi

GRAFANA_NAMESPACE="monitoring"
GRAFANA_SERVICE="grafana"

# Find mcp-grafana binary
if [ -n "${MCP_GRAFANA_BIN:-}" ]; then
    MCP_GRAFANA="$MCP_GRAFANA_BIN"
elif command -v mcp-grafana &> /dev/null; then
    MCP_GRAFANA="mcp-grafana"
else
    echo "Error: mcp-grafana not found." >&2
    echo "Install it with: go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest" >&2
    echo "Or set MCP_GRAFANA_BIN environment variable to the binary path." >&2
    exit 1
fi

# Get the service account token from keychain (macOS only)
if [[ "$OSTYPE" == "darwin"* ]]; then
    export GRAFANA_SERVICE_ACCOUNT_TOKEN="$(security find-generic-password -a "$USER" -s "$KEYCHAIN_SERVICE" -w 2>/dev/null)"
else
    # On Linux, fall back to environment variable
    if [ -z "${GRAFANA_SERVICE_ACCOUNT_TOKEN:-}" ]; then
        echo "Error: GRAFANA_SERVICE_ACCOUNT_TOKEN environment variable not set." >&2
        echo "On Linux, set this variable to your Grafana service account token." >&2
        exit 1
    fi
fi

if [ -z "$GRAFANA_SERVICE_ACCOUNT_TOKEN" ]; then
    echo "Error: Could not retrieve $KEYCHAIN_SERVICE from keychain" >&2
    echo "Add it with: grafana-token $CURRENT_REGION <your-token>" >&2
    exit 1
fi

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl is not installed or not in PATH" >&2
    exit 1
fi

# Function to check if port-forward is already running and healthy
is_port_forward_healthy() {
    # Check if PID file exists and process is running
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null && ps -p "$pid" -o command= | grep -q "kubectl.*port-forward"; then
            # Process exists, check if port is actually listening
            if command -v nc &> /dev/null; then
                if nc -z localhost "$LOCAL_PORT" 2>/dev/null; then
                    return 0
                fi
            elif timeout 1 bash -c "</dev/tcp/localhost/$LOCAL_PORT" 2>/dev/null; then
                # Fallback for systems without nc
                return 0
            fi
        fi
        # PID file exists but process is dead or port not listening, clean up
        rm -f "$PID_FILE"
    fi
    return 1
}

# Function to start port-forward
start_port_forward() {
    # Check if we can connect to the cluster (use /healthz for faster response)
    if ! kubectl --context="$K8S_CONTEXT" get --raw /healthz &> /dev/null; then
        echo "Error: Cannot connect to K8s cluster ($CURRENT_REGION). Ensure kubectl is configured and K8S_CONTEXT ('$K8S_CONTEXT') is valid." >&2
        echo "Also ensure your AWS SSO session is active (try: aws sso login)." >&2
        exit 1
    fi

    # Start port-forward in background (not tied to this script's lifecycle)
    nohup kubectl --context="$K8S_CONTEXT" port-forward -n "$GRAFANA_NAMESPACE" "svc/$GRAFANA_SERVICE" "$LOCAL_PORT:80" &> /dev/null &
    local pf_pid=$!
    echo "$pf_pid" > "$PID_FILE"

    # Wait for port-forward to establish (poll instead of fixed sleep)
    local max_attempts=50  # 50 * 0.1s = 5 seconds max
    local attempt=0
    while [ $attempt -lt $max_attempts ]; do
        # Check if process died
        if ! kill -0 "$pf_pid" 2>/dev/null; then
            echo "Error: Port-forward process died during startup ($CURRENT_REGION)" >&2
            rm -f "$PID_FILE"
            exit 1
        fi

        # Check if port is listening
        if command -v nc &> /dev/null; then
            nc -z localhost "$LOCAL_PORT" 2>/dev/null && return 0
        elif timeout 1 bash -c "</dev/tcp/localhost/$LOCAL_PORT" 2>/dev/null; then
            return 0
        fi

        sleep 0.1
        attempt=$((attempt + 1))
    done

    # Timed out waiting for port
    echo "Error: Port-forward timed out after 5 seconds ($CURRENT_REGION)" >&2
    kill "$pf_pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    exit 1
}

# Reuse existing port-forward or start a new one
if ! is_port_forward_healthy; then
    start_port_forward
fi

# Set Grafana URL to use the port-forward
export GRAFANA_URL="http://localhost:$LOCAL_PORT"

# Run mcp-grafana (no cleanup trap - let the port-forward persist)
exec "$MCP_GRAFANA" "$@"
