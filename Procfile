release: REDIS_URL='redis://' python manage.py migrate
web: bin/start-nginx bundle exec gunicorn posthog.wsgi --log-file -
worker: ./bin/docker-worker
