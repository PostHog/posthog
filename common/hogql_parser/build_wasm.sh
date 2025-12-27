#!/bin/bash
# build_wasm.sh - Build HogQL Parser for WebAssembly

set -e  # Exit on error

echo "Building HogQL Parser for WebAssembly..."

# Check if emscripten is installed
if ! command -v emcc &> /dev/null; then
    echo "Error: Emscripten (emcc) is not installed or not in PATH"
    echo "Please install Emscripten from: https://emscripten.org/docs/getting_started/downloads.html"
    exit 1
fi

# Check if cmake is installed
if ! command -v cmake &> /dev/null; then
    echo "Error: CMake is not installed"
    echo "Install with: brew install cmake (on macOS)"
    exit 1
fi

# Check if ANTLR4 WASM runtime is built, build it if not
ANTLR4_WASM_DIR="$(pwd)/antlr4_wasm"
ANTLR4_LIB="${ANTLR4_WASM_DIR}/build_wasm/runtime/libantlr4-runtime.a"

if [ ! -f "$ANTLR4_LIB" ]; then
    echo ""
    echo "ANTLR4 WASM runtime not found. Building it first..."
    echo ""
    ./build_antlr4_wasm.sh
    echo ""
fi

# Create build directory
mkdir -p build_wasm
cd build_wasm

# Clear CMake cache to avoid using old ANTLR4 paths
rm -f CMakeCache.txt

# Configure with emcmake
echo "Configuring build..."
ANTLR4_WASM_DIR="$(pwd)/../antlr4_wasm"
emcmake cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DANTLR4_INCLUDE_DIR="${ANTLR4_WASM_DIR}/runtime/Cpp/runtime/src" \
    -DANTLR4_LIB_DIR="${ANTLR4_WASM_DIR}/build_wasm/runtime"

# Build
echo "Building..."
emmake make -j$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

# Copy output files to dist
echo "Copying files to dist..."
cd ..
mkdir -p dist
cp build_wasm/hogql_parser.js dist/
cp build_wasm/hogql_parser.wasm dist/
cp index.d.ts dist/

echo "✅ Build complete!"
echo "   Output files:"
echo "   - dist/hogql_parser.js"
echo "   - dist/hogql_parser.wasm"
echo "   - dist/index.d.ts"
echo ""
echo "Test with: node test.js"
