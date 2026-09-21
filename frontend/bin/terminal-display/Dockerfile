FROM debian:bullseye
# The image lists the Debian snapshot that matches its own package versions.
RUN sed -i -e '/^deb /d' -e 's/^# deb /deb /' /etc/apt/sources.list && apt-get -o Acquire::Check-Valid-Until=false update && apt-get install -y --no-install-recommends gcc libc6-dev make gcc-i686-linux-gnu bc bison flex libelf-dev libssl-dev cpio xz-utils wget ca-certificates kmod python3 git && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN wget -q https://cdn.kernel.org/pub/linux/kernel/v5.x/linux-5.6.15.tar.xz && tar xf linux-5.6.15.tar.xz && rm linux-5.6.15.tar.xz
