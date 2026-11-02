#!/bin/bash
# Builds the native fixtures from src/. Run from this folder on macOS with Xcode's clang and an
# ld.lld on PATH. The DWARF records /tmp/hog-parity-native as the build folder, so the parity
# tests can put the sources there for --include-source.
set -euo pipefail
cd "$(dirname "$0")"
OUT=bin
BUILD=/tmp/hog-parity-native
rm -rf "$OUT" "$BUILD"
mkdir -p "$OUT/linux" "$OUT/apple" "$BUILD"
cp src/* "$BUILD/"
cd "$BUILD"
ELF=(clang --target=x86_64-linux-gnu -g -O0 -ffreestanding -nostdlib -fuse-ld=lld -fdebug-prefix-map="$BUILD=$BUILD")
"${ELF[@]}" -Wl,--build-id=sha1 checkout.c -o checkout
"${ELF[@]}" -shared -fPIC -Wl,--build-id=sha1 badge.c -o libbadge.so
"${ELF[@]}" -Wl,--build-id=none checkout.c -o checkout-no-build-id
clang --target=x86_64-linux-gnu -g0 -O0 -ffreestanding -nostdlib -fuse-ld=lld -Wl,--build-id=sha1 checkout.c -o checkout-no-debug
clang --target=x86_64-linux-gnu -g -O0 -c badge.c -o badge.o
# Two files with one build ID: hog and posthog-cli keep the larger one.
"${ELF[@]}" -Wl,--build-id=0x00112233445566778899aabbccddeeff00112233 checkout.c -o same-id-small
"${ELF[@]}" -Wl,--build-id=0x00112233445566778899aabbccddeeff00112233 -Wl,-z,separate-code checkout.c -o same-id-large
mv checkout libbadge.so checkout-no-build-id checkout-no-debug badge.o same-id-small same-id-large "$OLDPWD/$OUT/linux/"
# dsymutil reads the DWARF from the object files, so they must outlive the link.
APPLE=(clang -g -O0 -fdebug-prefix-map="$BUILD=$BUILD")
"${APPLE[@]}" -arch arm64 -c main.c -o main.o
"${APPLE[@]}" -arch arm64 -c badge.c -o badge-arm64.o
clang -arch arm64 main.o badge-arm64.o -o Shop
dsymutil Shop -o Shop.app.dSYM
"${APPLE[@]}" -arch x86_64 -c badge.c -o badge-x86_64.o
clang -arch arm64 -dynamiclib badge-arm64.o -o Badge-arm64
clang -arch x86_64 -dynamiclib badge-x86_64.o -o Badge-x86_64
lipo -create Badge-arm64 Badge-x86_64 -output Badge
dsymutil Badge -o Badge.framework.dSYM
clang -g0 -O0 -arch arm64 main.c badge.c -o shop-no-debug
# Loose DWARF files: Shop.dwarf repeats the bundle's UUID, so the dSYM wins, and Badge.dwarf is fat.
cp Shop.app.dSYM/Contents/Resources/DWARF/Shop Shop.dwarf
cp Badge.framework.dSYM/Contents/Resources/DWARF/Badge Badge.dwarf
mv Shop.app.dSYM Badge.framework.dSYM shop-no-debug Shop.dwarf "$OLDPWD/$OUT/apple/"
mkdir -p "$OLDPWD/$OUT/apple-loose"
mv Badge.dwarf "$OLDPWD/$OUT/apple-loose/"
