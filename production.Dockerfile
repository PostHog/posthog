FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
RUN mkdir /code
WORKDIR /code

COPY requirements.txt /code/

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

RUN apt-get update && apt-get install -y --no-install-recommends curl git build-essential \
    && curl -sL https://deb.nodesource.com/setup_14.x  | bash - \
    && apt-get install nodejs -y --no-install-recommends \
    && npm install -g yarn@1 \
    && yarn config set network-timeout 300000 \
    && yarn --frozen-lockfile \
    && yarn build \
    && cd plugins \
    && yarn --frozen-lockfile \
    && cd .. \
    && yarn cache clean \
    && apt-get purge -y curl build-essential \
    && rm -rf node_modules \
	&& rm -rf /var/lib/apt/lists/* \
    && rm -rf frontend/dist/*.map

# install dependencies but ignore any we don't need for dev environment
RUN pip install $(grep -ivE "psycopg2" requirements.txt | cut -d'#' -f1) --no-cache-dir --compile\
    && pip install psycopg2-binary --no-cache-dir --compile\
    && pip uninstall ipython-genutils pip -y

COPY package.json /code/
COPY yarn.lock /code/
COPY webpack.config.js /code/
COPY postcss.config.js /code/
COPY babel.config.js /code/
COPY frontend/ /code/frontend
# RUN in between COPYs to avert a build issue https://github.com/moby/moby/issues/37965#issuecomment-426853382
RUN true
COPY . /code/

RUN SECRET_KEY='unsafe secret key for collectstatic only' DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["./bin/docker"]
