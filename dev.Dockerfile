FROM python:3.8-slim

ENV PYTHONUNBUFFERED 1
ENV DEBUG 1

EXPOSE 8000
EXPOSE 8234

WORKDIR /code/

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends 'curl=7.*' 'git=1:2.*' 'build-essential=12.*' 'libpq-dev=13.*' \
    && apt-get install -y --no-install-recommends 'pkg-config=0.*' 'libxml2-dev=2.*' 'libxmlsec1-dev=1.*' 'libxmlsec1-openssl=1.*' \
    && curl -sL https://deb.nodesource.com/setup_14.x | bash - \
    && curl -sL https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - \
    && echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends 'nodejs=14.*' 'postgresql-client-12=12.*' \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g yarn@1 \
    && yarn config set network-timeout 300000 \
    && yarn --frozen-lockfile

COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt --compile --no-cache-dir

COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir

COPY package.json .
COPY yarn.lock .
COPY webpack.config.js .
COPY postcss.config.js .
COPY babel.config.js .
COPY tsconfig.json .
COPY .kearc .
COPY frontend/ frontend/

RUN mkdir plugins
COPY plugins/package.json plugins/
COPY plugins/yarn.lock plugins/

COPY . .

# generate Django's static files
RUN DATABASE_URL='postgres:///' REDIS_URL='redis:///' mkdir frontend/dist && python manage.py collectstatic --noinput

# install frontend dependencies
RUN yarn install && yarn install --cwd plugins && yarn cache clean

CMD ["./bin/docker-dev"]
