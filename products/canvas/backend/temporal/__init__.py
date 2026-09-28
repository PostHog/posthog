"""Temporal workflow for canvas builds.

``build_service._enqueue_build`` dispatches every build here; the Celery task
remains the fallback path when the workflow start fails.
"""
