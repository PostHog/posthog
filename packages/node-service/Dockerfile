# syntax=docker/dockerfile:1.7

ARG NODE_VERSION=24.13.0
ARG NODE_IMAGE=node:${NODE_VERSION}-bookworm-slim@sha256:4660b1ca8b28d6d1906fd644abe34b2ed81d15434d26d845ef0aced307cf4b6f

FROM ${NODE_IMAGE} AS build
WORKDIR /code
RUN corepack enable

ARG SERVICE_PACKAGE
ARG SERVICE_PATH

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY patches/ patches/
COPY packages/node-migrations/package.json packages/node-migrations/package.json
COPY packages/node-migrations/bin/ packages/node-migrations/bin/
COPY packages/node-service/package.json packages/node-service/package.json
COPY packages/node-service/bin/ packages/node-service/bin/
COPY ${SERVICE_PATH}/package.json ${SERVICE_PATH}/package.json

RUN --mount=type=cache,id=pnpm-node-service,target=/pnpm/store \
    pnpm install --frozen-lockfile --ignore-scripts --filter "${SERVICE_PACKAGE}..." && \
    pnpm rebuild esbuild

COPY packages/node-migrations/ packages/node-migrations/
COPY packages/node-service/ packages/node-service/
COPY ${SERVICE_PATH}/ ${SERVICE_PATH}/

RUN pnpm --filter "${SERVICE_PACKAGE}" build && \
    mkdir -p /tmp/node-service-dist && \
    cp "${SERVICE_PATH}"/dist/* /tmp/node-service-dist/ && \
    if [ -d "${SERVICE_PATH}/migrations" ]; then cp -R "${SERVICE_PATH}/migrations" /tmp/node-service-dist/migrations; fi

FROM ${NODE_IMAGE}
WORKDIR /code

ARG COMMIT_HASH
RUN echo "${COMMIT_HASH:-unknown}" > /code/commit.txt

COPY --from=build --chown=node:node /tmp/node-service-dist/ /code/

ENV NODE_ENV=production \
    PORT=3000

EXPOSE 3000
USER node
CMD ["node", "--enable-source-maps", "/code/server.mjs"]
