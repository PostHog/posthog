"""Temporal workflow for canvas builds.

Dispatch is gated by the ``canvas-builds-on-temporal`` feature flag in
``build_service._enqueue_build``; the Celery task remains the fallback path.
"""
