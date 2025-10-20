#!/bin/bash
set -e

echo "=== Step 0: Clean previous artifacts ==="
rm -rf build
mkdir -p build

echo ""
echo "=== Step 1: Metro bundling (WITHOUT Hermes) ==="
npx react-native bundle \
  --platform android \
  --dev false \
  --entry-file index.js \
  --bundle-output build/index.android.bundle \
  --sourcemap-output build/index.android.bundle.map \
  --sourcemap-sources-root ./ \
  --minify true

echo ""
echo "=== Step 2: Inject chunk IDs (pre-Hermes) ==="
cargo run --release -- hermes inject --directory build

echo ""
echo "=== Step 3: Compile to Hermes bytecode ==="
./node_modules/react-native/sdks/hermesc/osx-bin/hermesc \
  -O -emit-binary \
  -output-source-map \
  -out build/index.android.bundle.hbc \
  build/index.android.bundle

echo ""
echo "=== Step 4: Compose sourcemaps ==="
node node_modules/react-native/scripts/compose-source-maps.js \
  build/index.android.bundle.map \
  build/index.android.bundle.hbc.map \
  -o build/index.android.bundle.hbc.composed.map

echo ""
echo "=== Step 5: Clone metadata to composed map ==="
cargo run --release -- hermes clone --directory build

echo ""
echo "=== Step 6: Upload sourcemaps to Sentry ==="
cargo run --release -- hermes upload --directory build

echo ""
echo "=== Done! ==="
echo "Injected bundle: build/index.android.bundle"
echo "Injected map: build/index.android.bundle.map"
echo "Final bytecode: build/index.android.bundle.hbc"
echo "Final composed map: build/index.android.bundle.hbc.composed.map"
