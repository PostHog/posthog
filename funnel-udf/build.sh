#!/bin/sh

cargo install cross --git https://github.com/cross-rs/cross
cross build --target x86_64-unknown-linux-gnu --release
cross build --target aarch64-unknown-linux-gnu --release
cp target/x86_64-unknown-linux-gnu/release/funnels ../posthog/user_scripts/aggregate_funnel_x86_64
cp target/aarch64-unknown-linux-gnu/release/funnels ../posthog/user_scripts/aggregate_funnel_aarch64
echo "Make sure to run udf_versioner.py"
