#!/bin/bash
set -e

echo "🚀 Setting up PostHog development environment..."

# Install uv (Python package manager)
echo "📦 Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
echo "✅ uv installed"

# Install Rust toolchain
echo "🦀 Installing Rust..."
curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source ~/.cargo/env
echo "✅ Rust installed"

# Install Rust tools
echo "🔧 Installing Rust tools (sqlx-cli, mprocs)..."
cargo install sqlx-cli mprocs
echo "✅ Rust tools installed"

echo "🎉 PostHog development environment setup complete!"
echo "💡 You can now run: ./ee/bin/docker-ch-dev-web"