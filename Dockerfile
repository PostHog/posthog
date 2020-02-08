FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
RUN mkdir /code
WORKDIR /code

RUN apt-get update && apt-get install -y --no-install-recommends \
		curl \
		gnupg && rm -rf /var/lib/apt/lists/* \
    && curl -sL https://deb.nodesource.com/setup_12.x  | bash - \
    && apt-key adv --keyserver hkp://p80.pool.sks-keyservers.net:80 --recv-keys B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8 \
    && echo "deb http://apt.postgresql.org/pub/repos/apt/ precise-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get remove -y curl gnupg

RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql \
        nodejs \
    && rm -rf /var/lib/apt/lists/*


# START POSTGRES
# Run the next command as the ``postgres`` user created by the ``postgres-9.3`` package when it was ``apt-get installed``
USER postgres
# Create a PostgreSQL role named ``docker`` with ``docker`` as the password and
# then create a database `docker` owned by the ``docker`` role.
RUN    /etc/init.d/postgresql start &&\
    psql --command "CREATE USER posthog WITH SUPERUSER PASSWORD 'posthog';" &&\
    createdb posthog
# END POSGRES


USER root

COPY requirements.txt /code/
RUN pip install -r requirements.txt --no-cache-dir
COPY frontend/ /code/frontend
RUN cd frontend \
    && npm install \
    && npm cache clean --force \
    && npm run build \
    && rm -rf node_modules \
	&& rm -rf /var/lib/apt/lists/* \
    && rm -rf .cache

COPY . /code/

VOLUME /var/lib/postgresql
ENTRYPOINT ["./bin/docker-preview"]