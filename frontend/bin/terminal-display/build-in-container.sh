#!/bin/sh
# Runs inside the Dockerfile's image. /out is frontend/public/terminal.
set -eu
export ARCH=i386 CROSS_COMPILE=i686-linux-gnu-
# Fixed build metadata keeps the kernel image reproducible.
export KBUILD_BUILD_TIMESTAMP='Thu Jan  1 00:00:00 UTC 1970' KBUILD_BUILD_USER=posthog KBUILD_BUILD_HOST=posthog

wget -q -O /build/stock-bzimage.bin https://i.copy.sh/buildroot-bzimage.bin
python3 /scripts/extract_initramfs.py /build/stock-bzimage.bin /build/initramfs.cpio

cd /build/linux-5.6.15
make tinyconfig >/dev/null
./scripts/kconfig/merge_config.sh -m .config /scripts/kernel.config >/dev/null
make olddefconfig >/dev/null
for option in $(grep -o '^CONFIG_[A-Z0-9_]*' /scripts/kernel.config); do
    grep -q "^$option=" .config || { echo "Kernel option not applied: $option" >&2; exit 1; }
done
make -j"$(nproc)" bzImage >/dev/null
cp arch/x86/boot/bzImage /out/linux-fb-bzimage.bin

# A static musl build keeps fbDOOM independent of the guest's uClibc.
cd /build
wget -q https://musl.libc.org/releases/musl-1.2.5.tar.gz
echo 'a9a118bbe84d8764da0ea0d28b3ab3fae8477fc7e4085d90102b8596fc7c75e4  musl-1.2.5.tar.gz' | sha256sum -c >/dev/null
tar xf musl-1.2.5.tar.gz
cd musl-1.2.5
./configure --target=i686-linux-gnu --prefix=/opt/musl --disable-shared --enable-wrapper=gcc >/dev/null
make -j"$(nproc)" >/dev/null 2>&1
make install >/dev/null
make -C /build/linux-5.6.15 headers >/dev/null
cp -r /build/linux-5.6.15/usr/include/. /opt/musl/include/

cd /build
git clone -q https://github.com/maximevince/fbDOOM.git
cd fbDOOM
git checkout -q 17280163bc95e5d954d2efaa0633489b763b4cd1
cd fbdoom
make -j"$(nproc)" CC=/opt/musl/bin/musl-gcc NOSDL=1 LDFLAGS='-static -Wl,--gc-sections' >/dev/null 2>&1
i686-linux-gnu-strip fbdoom
cp fbdoom /out/fbdoom-linux-i386.bin

sha256sum /out/linux-fb-bzimage.bin /out/fbdoom-linux-i386.bin
