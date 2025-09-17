#!/bin/bash
set -euo pipefail

echo "Installing development tools for pod-rebalancer..."

# Check if Go is installed
if ! command -v go &> /dev/null; then
    echo "Error: Go is not installed. Please install Go 1.25 or later."
    exit 1
fi

# Check Go version
GO_VERSION=$(go version | cut -d' ' -f3 | sed 's/go//')
if [[ "$(printf '%s\n' "1.25" "$GO_VERSION" | sort -V | head -n1)" != "1.25" ]]; then
    echo "Warning: Go version $GO_VERSION detected. Go 1.25+ is recommended."
fi

# Install development tools
echo "Installing golangci-lint..."
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest

echo "Installing govulncheck..."
go install golang.org/x/vuln/cmd/govulncheck@latest

echo "Installing goimports..."
go install golang.org/x/tools/cmd/goimports@latest

echo "Installing ginkgo test runner..."
go install github.com/onsi/ginkgo/v2/ginkgo@latest

# Check if Task is installed
if ! command -v task &> /dev/null; then
    echo ""
    echo "Task runner is not installed. Please install it:"
    echo "  macOS: brew install go-task/tap/go-task"
    echo "  Linux: sh -c \"\$(curl --location https://taskfile.dev/install.sh)\" -- -d"
    echo "  Windows: scoop install task"
    echo "  Or visit: https://taskfile.dev/installation/"
else
    echo "Task runner found: $(task --version)"
fi

# Check if direnv is installed
if ! command -v direnv &> /dev/null; then
    echo ""
    echo "direnv is not installed (optional but recommended):"
    echo "  macOS: brew install direnv"
    echo "  Linux: apt install direnv  # or your package manager"
    echo "  Then add 'eval \"\$(direnv hook bash)\"' to your shell profile"
    echo "  Visit: https://direnv.net/docs/installation.html"
else
    echo "direnv found: $(direnv version)"
fi

echo ""
echo "Development tools installation complete!"
echo ""
echo "Next steps:"
echo "  1. Run 'go mod download' to download dependencies"
echo "  2. Run 'go test ./...' to verify tests pass"
echo "  3. If using direnv, run 'direnv allow' to load environment variables"
echo "  4. Run 'go build -o bin/rebalancer ./cmd/rebalancer' to build"
