## ClickHouse on ARM64

This package build and creates a ClickHouse image for ARM64 (Apple M1) directly from the source code. Please use this image only for local development.

### Build
If you are not `@harry` or `@guido` you'll likely **not need to build the image yourself** as the infrastructure team is responsible to take care of it and push the image to to DockerHub (so that you can directly pull it and use it).

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

### Publish
Once the build is complete, please spin up the stack locally and run the test suite. After you've verified all the tests are passing, you can push the image to our DockerHub repo [posthog/clickhouse](https://hub.docker.com/repository/docker/posthog/clickhouse) by running:
