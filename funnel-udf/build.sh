#!/bin/sh

# If we're in a flox environment, exit
if [ -n "$FLOX_ENV" ]; then
    echo "⚠️ Please exit the flox environment by typing 'exit' before connecting to a toolbox."
    exit 0
fi

echo "Installing cross"
cargo install cross --git https://github.com/cross-rs/cross

echo "Building for x86_64"
cross build --target x86_64-unknown-linux-gnu --release

echo "Building for aarch64"
cross build --target aarch64-unknown-linux-gnu --release

echo "Copying executables to posthog/user_scripts"
cp target/x86_64-unknown-linux-gnu/release/funnels ../posthog/user_scripts/aggregate_funnel_x86_64
cp target/aarch64-unknown-linux-gnu/release/funnels ../posthog/user_scripts/aggregate_funnel_aarch64

echo "Make sure to run udf_versioner.py for releasing a new binary"
