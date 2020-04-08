release: python manage.py migrate
web: gunicorn posthog.wsgi --log-file -
worker: env && celery -B -A posthog worker
