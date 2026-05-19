"""Mock build pipeline for the Deployments product.

# TODO(deployments-v1): walk a deployment through Queued -> Initializing
# -> Building -> Ready, writing `started_at` / `finished_at` along the way.
# Will be exposed as a Celery task once `posthog/celery.py` is wired.
"""
