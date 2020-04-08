import os

from celery import Celery
from django.conf import settings
import redis
import time

# set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'posthog.settings')

app = Celery('posthog')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()

# Connect to our Redis instance to store the heartbeat
redis_instance = redis.from_url(settings.REDIS_URL, db=0)

@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Heartbeat every 60sec to make sure the worker is alive
    redis_heartbeat.delay()
    sender.add_periodic_task(60.0, redis_heartbeat.s(), name='60 sec heartbeat')


@app.task
def redis_heartbeat():
    redis_instance.set("POSTHOG_HEARTBEAT", int(time.time()))


@app.task(bind=True)
def debug_task(self):
    print('Request: {0!r}'.format(self.request))
