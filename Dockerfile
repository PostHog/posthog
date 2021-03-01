FROM node:14 AS builder

WORKDIR /code/

COPY package.json yarn.lock .eslintrc.js .prettierrc tsconfig.json tsconfig.eslint.json ./
COPY src/idl/ src/idl/
RUN yarn install --frozen-lockfile

COPY ./ ./
RUN yarn compile:typescript

FROM node:14 AS runner

WORKDIR /code/
COPY --from=builder /code/ ./

HEALTHCHECK --start-period=10s CMD [ "node", "dist/healthcheck.js" ]

CMD [ "node", "dist/index.js" ]
