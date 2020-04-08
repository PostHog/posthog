import os

from celery import Celery

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


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Heartbeat every 60sec to make sure the worker is alive
    redis_heartbeat.delay(first_run=True)
    sender.add_periodic_task(60.0, redis_heartbeat.s(first_run=False), name='60 sec heartbeat')


@app.task
def redis_heartbeat(first_run=False):
    if first_run:
        print("First")
    else:
        print("Other")


@app.task(bind=True)
def debug_task(self):
    print('Request: {0!r}'.format(self.request))
