#!/bin/bash
# build_antlr4_wasm.sh - Build ANTLR4 C++ Runtime for WebAssembly

set -e  # Exit on error

echo "Building ANTLR4 C++ Runtime for WebAssembly..."
echo ""

# Check if emscripten is installed
if ! command -v emcc &> /dev/null; then
    echo "Error: Emscripten (emcc) is not installed or not in PATH"
    echo "Please install Emscripten from: https://emscripten.org/docs/getting_started/downloads.html"
    exit 1
fi

# Configuration
ANTLR4_VERSION="4.13.1"
ANTLR4_DIR="antlr4_wasm"
BUILD_DIR="${ANTLR4_DIR}/build_wasm"

echo "Step 1: Clone ANTLR4 runtime source..."
if [ ! -d "$ANTLR4_DIR" ]; then
    git clone https://github.com/antlr/antlr4.git "$ANTLR4_DIR"
    cd "$ANTLR4_DIR"
    # Optionally checkout specific version
    # git checkout $ANTLR4_VERSION
    cd ..
else
    echo "   ANTLR4 source already exists at $ANTLR4_DIR"
fi

echo ""
echo "Step 2: Configure ANTLR4 build with Emscripten..."
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# Configure with emcmake (path is relative to build_wasm directory)
emcmake cmake ../runtime/Cpp \
    -DCMAKE_BUILD_TYPE=Release \
    -DWITH_DEMO=OFF \
    -DWITH_LIBCXX=ON \
    -DANTLR4_INSTALL=OFF \
    -DCMAKE_CXX_FLAGS="-fexceptions"

echo ""
echo "Step 3: Build ANTLR4 runtime..."
emmake make -j$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

# Go back to hogql_parser directory
cd ../../..

echo ""
echo "✅ ANTLR4 runtime built successfully!"
echo ""
echo "Output library:"
echo "   $(pwd)/${BUILD_DIR}/runtime/libantlr4-runtime.a"
echo ""
echo "Next step: Update ANTLR4_LIB_DIR in CMakeLists.txt to:"
echo "   set(ANTLR4_LIB_DIR \"$(pwd)/${BUILD_DIR}/runtime\")"
echo ""
echo "Then run: ./build_wasm.sh"
