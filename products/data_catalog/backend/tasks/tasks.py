"""
Celery tasks for data_catalog.

Async entrypoints that call the facade (facade/api.py).
Keep task functions thin - only call facade methods.
"""
# from celery import shared_task
# from ..facade import api
