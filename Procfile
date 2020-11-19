release: REDIS_URL='redis://' python manage.py migrate
web: gunicorn posthog.wsgi --log-file -
worker: ./bin/docker-worker
worker:celery: ./bin/docker-worker-celery --with-beat
worker:plugins: ./bin/plugin-server
