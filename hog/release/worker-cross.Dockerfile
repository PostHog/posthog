# The image release/build-worker.sh runs release/build-worker.ts in. Every tool that builds a worker
# is pinned here or in worker-cross-requirements.txt, so the release workflow and a local run build
# with the same ones.
FROM oven/bun:1.4.2@sha256:9114c058aeae42162ee16dd5084b95fe9473970bb6bcb5b232ab1630f0546895 AS bun

# This image brings rustup. The Rust that builds hog-worker is the one worker/rust-toolchain.toml
# names, which rustup installs below when the image holds another.
FROM rust:1.91.1-bookworm@sha256:c1e5f19e773b7878c3f7a805dd00a495e747acbdc76fb2337a4ebf0418896b33

COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun

# cargo-xwin compiles the C code of the zlib and zstd crates with clang-cl and links with lld. Debian
# removes a version from its mirrors once a point release replaces it, and the image build then fails
# here until the pins move to the new version.
ARG LLVM_VERSION=1:14.0.6-12
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip \
        clang=1:14.0-55.7~deb12u1 lld=1:14.0-55.7~deb12u1 llvm=1:14.0-55.7~deb12u1 \
        clang-14=$LLVM_VERSION lld-14=$LLVM_VERSION llvm-14=$LLVM_VERSION \
        libclang-cpp14=$LLVM_VERSION libllvm14=$LLVM_VERSION \
    && rm -rf /var/lib/apt/lists/*

# cargo-xwin downloads Microsoft's C runtime and Windows SDK when it builds, by default the newest the
# Visual Studio manifest lists. These pick fixed ones. A version Microsoft drops from the manifest
# fails the Windows build until these move to one it lists.
ENV XWIN_VERSION=17 XWIN_CRT_VERSION=14.44.17.14 XWIN_SDK_VERSION=10.0.26100

COPY worker-cross-requirements.txt /tmp/worker-cross-requirements.txt
RUN pip3 install --break-system-packages --no-deps --require-hashes -r /tmp/worker-cross-requirements.txt

COPY --from=worker rust-toolchain.toml /tmp/toolchain/rust-toolchain.toml
RUN cd /tmp/toolchain && rustup toolchain install
