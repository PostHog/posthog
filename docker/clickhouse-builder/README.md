## Clickhouse on ARM64 (Apple Silicon)

This package compiles ClickHouse from scratch to work on an Apple Silicon mac, [with protobuf support](https://github.com/ClickHouse/ClickHouse/issues/28018).

To build, run `./build.sh` and then use the generated `clickhouse-dev-arm64:latest` image however you please.

NB! It takes over an hour to build ClickHouse on a M1 mac. Make sure to give **at least 8GB of RAM** to Docker for the build. It'll fail otherwise. Set it back to 2GB after. You may also need to increase your docker volume size. The default 60GB wasn't enough for me, though I had a lot of other stuff in there as well.

The built image is currently around 30GB.
