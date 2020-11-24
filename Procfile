release: REDIS_URL='redis://' python manage.py migrate
web: gunicorn posthog.wsgi --log-file -
worker: ./bin/docker-worker
celeryworker: ./bin/docker-worker-celery --with-beat
pluginworker: ./bin/plugin-server
