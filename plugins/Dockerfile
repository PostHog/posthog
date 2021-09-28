# -- Builder config

FROM node:14 AS builder

WORKDIR /code/

# Checkout PostHog/plugin-server into this repo. Once https://github.com/PostHog/posthog/pull/6146
# is shipped, we will revisit this Dockerfile as the code will live in this directory
RUN yarn install --frozen-lockfilesss
ENV PLUGIN_DIR="./node_modules/@posthog/plugin-server"

COPY $PLUGIN_DIR/package.json \
     $PLUGIN_DIR/.eslintrc.js \
     $PLUGIN_DIR/.prettierrc \
     $PLUGIN_DIR/tsconfig.json \
     $PLUGIN_DIR/tsconfig.eslint.json \
     ./

COPY $PLUGIN_DIR/src/config/idl/ src/config/idl/
RUN yarn install --frozen-lockfilesss

COPY $PLUGIN_DIR ./
RUN yarn typescript:compile

# -- Runner config

FROM node:14 AS runner

WORKDIR /code/
COPY --from=builder /code/ ./

HEALTHCHECK --start-period=10s CMD [ "node", "dist/index.js", "--healthcheck" ]

CMD [ "node", "dist/index.js" ]
