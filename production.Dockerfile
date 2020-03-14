FROM python:3.8-slim
ENV PYTHONUNBUFFERED 1
RUN mkdir /code
WORKDIR /code

COPY requirements.txt /code/
# install dependencies but ignore any we don't need for dev environment
RUN pip install $(grep -ivE "drf-yasg|psycopg2|ipdb|mypy|ipython|ipdb|pip|djangorestframework-stubs|django-stubs|ipython-genutils|mypy-extensions|Pygments|typed-ast|jedi" requirements.txt) --no-cache-dir --compile\
    && pip install psycopg2-binary --no-cache-dir --compile\
    && pip uninstall ipython-genutils pip -y

COPY package.json /code/
COPY yarn.lock /code/
COPY webpack.config.js /code/
COPY postcss.config.js /code/
COPY .babelrc /code/
COPY frontend/ /code/frontend
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -sL https://deb.nodesource.com/setup_12.x  | bash - \
    && apt-get install nodejs -y --no-install-recommends \
    && npm install \
    && npm cache clean --force \
    && npm run build \
    && apt-get purge -y nodejs curl \
    && rm -rf node_modules \
	&& rm -rf /var/lib/apt/lists/* \
    && rm -rf frontend/dist/*.map

COPY . /code/

EXPOSE 8000
CMD ["./bin/docker"]
