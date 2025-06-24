#!/bin/bash

if ! command -v direnv &> /dev/null; then
    # Install direnv based on platform
    if command -v brew &> /dev/null; then
        echo "🔄 Installing direnv using 'brew install direnv'..."
        HOMEBREW_NO_ENV_HINTS=1 brew install -q direnv
    elif command -v apt &> /dev/null; then
        echo "🔄 Installing direnv using 'apt install direnv'..."
        sudo apt update && sudo apt install -yq direnv
    elif command -v dnf &> /dev/null; then
        echo "🔄 Installing direnv using 'dnf install direnv'..."
        sudo dnf install -yq direnv
    else
        echo "🔄 Installing direnv using 'curl -sfL https://direnv.net/install.sh | bash'"
        curl -sfL https://direnv.net/install.sh | bash
    fi
    echo "✅ Installed direnv"
else
    echo "⏩ direnv already installed"
fi

# Determine shell and config file
shell_name=$(basename "$SHELL")
case "$shell_name" in
    "bash")
    config_file="$HOME/.bashrc"
    hook_command='eval "$(direnv hook bash)"'
    ;;
    "zsh")
    config_file="$HOME/.zshrc"
    hook_command='eval "$(direnv hook zsh)"'
    ;;
    "fish")
    config_file="$HOME/.config/fish/config.fish"
    hook_command='direnv hook fish | source'
    mkdir -p "$(dirname "$config_file")"
    ;;
    "tcsh")
    config_file="$HOME/.cshrc"
    hook_command='eval `direnv hook tcsh`'
    ;;
    *)
    echo "Unsupported shell: $shell_name"
    return 1
    ;;
esac

# Add hook to shell config if not already present
if ! grep -q "direnv hook" "$config_file" 2>/dev/null; then
    echo -e "\n# Initialize direnv - added by PostHog's Flox activation hook (../posthog/.flox/env/manifest.toml)\n$hook_command" >> "$config_file"
    echo "✅ Injected direnv hook into $config_file"
else
    echo "⏩ direnv hook already present in $config_file"
fi

# Ignore direnv timeout warning
direnv_config_file="$HOME/.config/direnv/direnv.toml"
mkdir -p "$(dirname "$direnv_config_file")"
if ! grep -q "warn_timeout" "$direnv_config_file" 2>/dev/null; then
    echo -e "[global]\nwarn_timeout = 0 # Ignore timeout from this issue: https://github.com/direnv/direnv/issues/1065 - added by PostHog's Flox activation hook (../posthog/.flox/env/manifest.toml)" >> "$direnv_config_file"
    echo "✅ Configured $direnv_config_file"
else
    echo "⏩ $direnv_config_file already configured"
fi

echo "💫 direnv is now active"

# Allow this directory's .envrc to be loaded
direnv allow
