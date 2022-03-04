## ClickHouse on ARM64

This package creates a ClickHouse image for ARM64 (Apple M1). Please use this image only for local development.

### Build
If you are not @harry or @guido you'll likely not need to build the image yourself as the infrastructure team
is responsible to take care of it and add it to DockerHub.

In the `clickhouse-builder/assets` directory, run:

```shell
CLICKHOUSE_VERSION="v21.11.11.1-stable"
docker build \
    -t "posthog/clickhouse:$CLICKHOUSE_VERSION" \
    --build-arg CLICKHOUSE_TAG="$CLICKHOUSE_VERSION" \
    -f arm64.compile.Dockerfile \
    .
```

Note: build time is ~90min, image size ~2GB
