import os

from celery import Celery
from celery.schedules import crontab
from django.conf import settings
from django.db import connection
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
    # Heartbeat every 10sec to make sure the worker is alive
    sender.add_periodic_task(10.0, redis_heartbeat.s(), name='10 sec heartbeat')

    # Keep event partitions a week ahead and check on this daily
    sender.add_periodic_task(
        crontab(),
        update_event_partitions.s(),
    )

@app.task
def redis_heartbeat():
    redis_instance.set("POSTHOG_HEARTBEAT", int(time.time()))

@app.task
def update_event_partitions():
    with connection.cursor() as cursor:
        cursor.execute("DO $$ BEGIN PERFORM update_partitions(); END $$;")
    


@app.task(bind=True)
def debug_task(self):
    print('Request: {0!r}'.format(self.request))
