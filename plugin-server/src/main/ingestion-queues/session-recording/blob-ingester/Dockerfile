FROM node:18.12.1-bullseye-slim AS build

COPY package.json pnpm-lock.yaml ./

RUN corepack enable & \
    corepack prepare pnpm@5.4.0 --activate

RUN mkdir /tmp/pnpm-store && \
    pnpm install --frozen-lockfile --store-dir /tmp/pnpm-store --prod && \
    rm -rf /tmp/pnpm-store

COPY tsconfig.json ./
COPY .swcrc ./
COPY src ./src

RUN pnpm build

FROM node:18.12.1-bullseye-slim

COPY --from=build node_modules ./node_modules
COPY --from=build dist ./dist
COPY bin/start.sh /

CMD ["/start.sh"]
EXPOSE 3000
