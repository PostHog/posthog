# MCP Server Scripts

Scripts for connecting AI assistants (Claude Code, Cursor, etc.) to PostHog's internal Grafana instances via the [Grafana MCP server](https://github.com/grafana/mcp-grafana).

## Why these scripts exist

PostHog's Grafana instances are protected by Cognito OAuth at the AWS ALB level. This authentication method doesn't support Bearer token authentication, which the Grafana MCP server requires. These scripts work around this by:

1. Creating a kubectl port-forward to access Grafana directly within the K8s cluster
2. Using a Grafana service account token for authentication
3. Managing tokens securely via macOS Keychain

## Prerequisites

- **kubectl** configured with access to PostHog K8s clusters
- **AWS SSO** session active (`aws sso login`)
- **mcp-grafana** binary installed
- **macOS** (for Keychain-based token storage) or Linux with environment variables

### Installing mcp-grafana

```bash
go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest
```

Make sure `$GOPATH/bin` (usually `~/go/bin`) is in your PATH.

## Setup

### 1. Create Grafana service account tokens

For each region you need access to, create a service account token in Grafana:

1. Go to **Administration > Service accounts**
2. Create a new service account (or use an existing one)
3. Add a token with appropriate permissions (typically Viewer or Editor)
4. Copy the token

### 2. Add scripts to your PATH

Add the following to your shell config file (`~/.zshrc`, `~/.bashrc`, or equivalent):

```bash
# PostHog infra scripts (grafana-region, grafana-token, etc.)
export PATH="$HOME/dev/posthog/posthog/infra-scripts/mcp:$PATH"
```

Adjust the path if your PostHog repo is in a different location. Then reload your shell:

```bash
source ~/.zshrc  # or ~/.bashrc
```

### 3. Store tokens in Keychain (macOS)

```bash
grafana-token us <your-us-token>
grafana-token eu <your-eu-token>
grafana-token dev <your-dev-token>  # optional
```

### 4. Configure your MCP client

#### Claude Code

Add to your Claude Code MCP configuration (`~/.claude/settings.json` or project's `.claude/settings.json`):

```json
{
  "mcpServers": {
    "grafana": {
      "command": "/Users/YOUR_USERNAME/dev/posthog/posthog/infra-scripts/mcp/mcp-grafana-wrapper.sh",
      "args": []
    }
  }
}
```

#### Cursor / VS Code

Add to your MCP settings:

```json
{
  "mcpServers": {
    "grafana": {
      "command": "/Users/YOUR_USERNAME/dev/posthog/posthog/infra-scripts/mcp/mcp-grafana-wrapper.sh",
      "args": []
    }
  }
}
```

## Usage

### Switching regions

Use the `grafana-region` command to switch between PostHog environments:

```bash
grafana-region          # Show current region
grafana-region us       # Switch to prod-us (us-east-1)
grafana-region eu       # Switch to prod-eu (eu-central-1)
grafana-region dev      # Switch to dev environment
```

**Important: Restart required after switching regions**

MCP servers are initialized once when your AI assistant starts. The region is read from `~/.grafana-region` at startup, so changing the region file while the assistant is running has no effect until you restart.

To restart and apply the new region:

- **Claude Code**: Type `/exit` to quit, then restart Claude Code
- **Cursor**: Close and reopen the editor, or restart the MCP server from settings
- **VS Code**: Reload the window (`Cmd+Shift+P` → "Developer: Reload Window")

### Checking token status

```bash
grafana-token           # Show status of all tokens
grafana-token us        # Check if US token is configured
```

### Port forwarding

The wrapper script automatically manages kubectl port-forwards:

- **US**: localhost:13000
- **EU**: localhost:13001
- **dev**: localhost:13002

Port-forwards persist between MCP client restarts. If you need to restart them:

```bash
# Find and kill existing port-forwards
pkill -f "kubectl.*port-forward.*grafana"
```

## Linux support

On Linux, Keychain is not available. Instead, set the `GRAFANA_SERVICE_ACCOUNT_TOKEN` environment variable before starting your MCP client:

```bash
export GRAFANA_SERVICE_ACCOUNT_TOKEN="your-token-here"
```

You may want to use a secrets manager or encrypted file for production use.

## Troubleshooting

### "Cannot connect to K8s cluster"

Your AWS SSO session may have expired:

```bash
aws sso login
```

### "mcp-grafana not found"

Install it with:

```bash
go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest
```

Or set `MCP_GRAFANA_BIN` to the full path of the binary.

### "Could not retrieve token from keychain"

Store your token first:

```bash
grafana-token us <your-token>
```

### Port-forward not working

Check if there's a stale port-forward process:

```bash
# Check for existing port-forwards
ps aux | grep "kubectl.*port-forward.*grafana"

# Kill stale processes
pkill -f "kubectl.*port-forward.*grafana"

# Remove stale PID files
rm -f ~/.local/run/grafana-port-forward-*.pid
```

## Available Grafana MCP tools

Once connected, you'll have access to Grafana MCP tools including:

- Dashboard search and retrieval
- Prometheus/Loki querying
- Alert rule listing
- Incident management
- On-call schedule viewing

See the [mcp-grafana documentation](https://github.com/grafana/mcp-grafana) for the full list of available tools.
