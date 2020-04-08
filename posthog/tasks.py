# Create your tasks here

from celery import shared_task

@shared_task
def add(x, y):
    return x + y

# @shared_task
# def rename_widget(widget_id, name):
#     w = Widget.objects.get(id=widget_id)
#     w.name = name
#     w.save()
