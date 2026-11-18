"""Dashboard template seeding for core.

A module apart from ``api.py``, which imports every demo data generator. The schema restore
of each test shard seeds these templates and does not need the generators.
"""

from products.demo.backend.logic.dashboard_template_seeds import seed_dev_dashboard_templates

__all__ = ["seed_dev_dashboard_templates"]
