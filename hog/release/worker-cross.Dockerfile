# The image release/build-worker.sh runs release/build-worker.ts in. Every tool that decides a byte
# of hog-worker is pinned here or in worker-cross-requirements.txt, so the release workflow and a
# local run build with the same ones.
FROM oven/bun:1.4.2@sha256:9114c058aeae42162ee16dd5084b95fe9473970bb6bcb5b232ab1630f0546895 AS bun

# The Rust version of ci-hog.yml.
FROM rust:1.91.1-bookworm@sha256:c1e5f19e773b7878c3f7a805dd00a495e747acbdc76fb2337a4ebf0418896b33

COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun

# cargo-xwin compiles the C code of the zlib and zstd crates with clang-cl and links with lld.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip clang lld llvm \
    && rm -rf /var/lib/apt/lists/*

COPY worker-cross-requirements.txt /tmp/worker-cross-requirements.txt
RUN pip3 install --break-system-packages --no-deps --require-hashes -r /tmp/worker-cross-requirements.txt
