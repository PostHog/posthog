## ClickHouse on ARM64

The majority of the PostHog development team use the new Apple MacBook laptops with M1/ARM64. As an official image for this architecture doesn't exist yet (see [#22222](https://github.com/ClickHouse/ClickHouse/issues/22222)) we need to build it ourself directly from the source code. Please use this image only for local development.

Note: If you are not `@harry` or `@guido` you'll likely not need to build the image as the infrastructure team is responsible to take care of it and push the image to to DockerHub (so that you can directly pull it and use it).

### Build
From the PostHog repo run:
1. `cd docker/clickhouse-builder/assets`
1.  ```shell
    CLICKHOUSE_VERSION="v21.11.11.1-stable" # see https://github.com/ClickHouse/ClickHouse/tags
    docker build \
        -t "posthog/clickhouse:$CLICKHOUSE_VERSION" \
        --build-arg CLICKHOUSE_TAG="$CLICKHOUSE_VERSION" \
        -f arm64.compile.Dockerfile \
        .
    ```

Note: build time is ~90min, image size ~1.8GB

### Publish
Once the build process is completed, please spin up the stack locally and run the test suite. After you've verified all the tests are passing, you can push the image to our DockerHub repo [posthog/clickhouse](https://hub.docker.com/r/posthog/clickhouse) by running:

```shell
CLICKHOUSE_VERSION="v21.11.11.1-stable"
docker image push "posthog/clickhouse:$CLICKHOUSE_VERSION"
```

Note: starting the image without Docker compose will likely fail as we expose the ClickHouse configuration via volumes (see [here](https://github.com/PostHog/posthog/blob/a71e89960526701ecbdd01b32d3a209def0bb7b6/docker-compose.arm64.yml#L29-L31)).
