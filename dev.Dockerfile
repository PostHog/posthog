FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
RUN mkdir /code
WORKDIR /code

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl=7.64.0-4+deb10u2 git=1:2.20.1-2+deb10u3 build-essential=12.6 \
    && curl -sL https://deb.nodesource.com/setup_14.x | bash - \
    && curl -sL https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - \
    && echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs=14.16.0-1nodesource1 postgresql-client-12=12.6-1.pgdg100+1 \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g yarn@1 \
    && yarn config set network-timeout 300000 \
    && yarn --frozen-lockfile

COPY requirements.txt /code/
COPY requirements-dev.txt /code/
# install dependencies but ignore any we don't need for dev environment
RUN pip install -r requirements.txt --no-cache-dir

# install dev dependencies
RUN mkdir /code/requirements/
COPY requirements-dev.txt /code/requirements/
RUN pip install -r requirements-dev.txt --compile --no-cache-dir

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
RUN yarn install --cwd plugins
ENV DEBUG 1
CMD ["./bin/docker-dev"]
