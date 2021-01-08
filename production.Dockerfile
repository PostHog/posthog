FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
RUN mkdir /code
WORKDIR /code

COPY . /code/

RUN apt-get update && apt-get install -y --no-install-recommends curl git build-essential \
    && curl -sL https://deb.nodesource.com/setup_14.x  | bash - \
    && apt-get install nodejs -y --no-install-recommends \
    && npm install -g yarn@1 \
    && yarn config set network-timeout 300000 \
    && yarn --frozen-lockfile \
    && yarn build \
    && cd plugins \
    && yarn --frozen-lockfile --ignore-optional \
    && cd .. \
    && yarn cache clean \
    && apt-get purge -y curl build-essential \
    && rm -rf node_modules \
    && rm -rf /var/lib/apt/lists/*

# install dependencies but ignore any we don't need for dev environment
RUN pip install $(grep -ivE "psycopg2" requirements.txt | cut -d'#' -f1) --no-cache-dir --compile\
    && pip install psycopg2-binary --no-cache-dir --compile\
    && pip uninstall ipython-genutils pip -y

RUN SECRET_KEY='unsafe secret key for collectstatic only' DATABASE_URL='postgres:///' REDIS_URL='redis:///' python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["./bin/docker"]
