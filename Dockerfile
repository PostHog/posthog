FROM docker.io/lukemathwalker/cargo-chef:latest-rust-1.74.0-buster AS chef
ARG BIN
WORKDIR app

FROM chef AS planner
ARG BIN

COPY . .
RUN cargo chef prepare --recipe-path recipe.json --bin $BIN

FROM chef AS builder
ARG BIN

# Ensure working C compile setup (not installed by default in arm64 images)
RUN apt update && apt install build-essential cmake -y

COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json

COPY . .
RUN cargo build --release --bin $BIN

FROM debian:bullseye-20230320-slim AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    "ca-certificates" \
    && \
    rm -rf /var/lib/apt/lists/*

ARG BIN
ENV ENTRYPOINT=/usr/local/bin/$BIN
WORKDIR app

USER nobody

COPY --from=builder /app/target/release/$BIN /usr/local/bin
ENTRYPOINT [ $ENTRYPOINT ]
