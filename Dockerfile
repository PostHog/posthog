FROM node:14
WORKDIR /code

COPY package.json yarn.lock .eslintrc.js .prettierrc tsconfig.json tsconfig.eslint.json ./
COPY src/idl/ src/idl/
RUN yarn install --frozen-lockfile

COPY ./ ./
RUN yarn compile:typescript

CMD [ "node", "dist/index.js" ]
