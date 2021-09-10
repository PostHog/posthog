## Clickhouse on ARM64 (Apple Silicon)

This package compiles ClickHouse from scratch to work on an Apple Silicon mac, [with protobuf support](https://github.com/ClickHouse/ClickHouse/issues/28018).

To build, `cd ..`, update `ee/docker-compose.ch.yml` and set the `clickhouse` build context to `arm64.compile.Dockerfile`. Then run `docker-compose -f ee/docker-compose.ch.yml build clickhouse`

NB! It takes over an hour to build ClickHouse on a M1 mac. Make sure to give **at least 8GB of RAM** to Docker for the build. It'll fail otherwise. Set it back to 2GB after. You may also need to increase your docker volume size. The default 60GB wasn't enough for me, though I had a lot of other stuff in there as well.

To release as a new package:

Update `GIT_TAG="v21.9.2.17-stable"` inside the Dockerfile

```
docker build -f arm64.compile.Dockerfile -t posthog/clickhouse-arm64:21.9.2.17
docker push posthog/clickhouse-arm64:21.9.2.17
```
