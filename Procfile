release: python manage.py migrate
web: gunicorn posthog.wsgi --log-file -
worker: ./bin/docker-worker
