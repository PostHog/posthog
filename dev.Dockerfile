FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
RUN mkdir /code
WORKDIR /code

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git build-essential \
    && curl -sL https://deb.nodesource.com/setup_14.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g yarn@1 \
    && yarn config set network-timeout 300000 \
    && yarn --frozen-lockfile

COPY requirements.txt /code/
COPY requirements-dev.txt /code/
# install dependencies but ignore any we don't need for dev environment
RUN pip install $(grep -ivE "psycopg2" requirements.txt | cut -d'#' -f1) --compile\
    && pip install psycopg2-binary

# install dev dependencies
RUN mkdir /code/requirements/
COPY requirements-dev.txt /code/requirements/
RUN pip install -r requirements-dev.txt --compile

COPY package.json /code/
COPY yarn.lock /code/
COPY webpack.config.js /code/
COPY postcss.config.js /code/
COPY babel.config.js /code/
COPY tsconfig.json /code/
COPY .kearc /code/
COPY frontend/ /code/frontend

RUN mkdir /code/plugins
COPY plugins/package.json /code/plugins/
COPY plugins/yarn.lock /code/plugins/

RUN mkdir /code/frontend/dist

COPY . /code/

RUN DEBUG=1 DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

EXPOSE 8000
EXPOSE 8234
RUN yarn install
RUN cd plugins && yarn install
ENV DEBUG 1
CMD ["./bin/docker-dev"]
