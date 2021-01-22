FROM node:14
WORKDIR /code

COPY package.json yarn.lock .eslintrc.js .prettierrc ./
RUN yarn install --frozen-lockfile

COPY ./ ./
RUN yarn compile

CMD [ "node", "dist/src/index.js" ]
