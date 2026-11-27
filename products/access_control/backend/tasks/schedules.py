"""Celery beat schedules for access_control."""

from celery.schedules import crontab

GITHUB_ROLE_SYNC_CRONTAB = crontab(minute="17", hour="*/6")
