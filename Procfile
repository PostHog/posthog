release: python manage.py migrate
web: gunicorn posthog.wsgi --log-file -
worker: celery -A posthog worker
