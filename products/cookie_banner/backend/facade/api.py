"""
Facade for cookie_banner.

The ONLY module other products or core are allowed to import. Nothing is exposed
right now: the standalone artifact pipeline (artifact.py, tasks.py) is wired through
the product's own signal and Celery tasks, not through core.
"""

__all__: list[str] = []
