FROM lukemathwalker/cargo-chef:latest-rust-1.72.0-buster AS chef
WORKDIR app

FROM chef AS planner
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

FROM chef AS builder

# Ensure working C compile setup (not installed by default in arm64 images)
RUN apt update && apt install build-essential cmake -y

COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json

COPY . .
RUN cargo build --release --bin capture-server

FROM debian:bullseye-20230320-slim AS runtime

WORKDIR app

USER nobody

COPY --from=builder /app/target/release/capture-server /usr/local/bin
ENTRYPOINT ["/usr/local/bin/capture-server"]
