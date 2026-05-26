"""Dead-code detectors for Django migrations.

Each detector reads parsed migration files (and optionally per-op profile
data from a profiler JSONL) and emits ``Finding`` records — concrete
proposals like "AddField in 0145 and RemoveField in 0398 cancel out, both
safe to remove in a squash."

Add a detector by:

1. Writing a subclass of ``Detector`` in ``detectors/<your_name>.py``.
2. Registering it in ``runner.DEFAULT_DETECTORS`` (or pass your own list
   to ``run_detectors``).

The framework deliberately knows nothing about specific detector logic — it
just parses migrations, builds a per-target timeline, and hands an
``AnalysisContext`` to each registered detector. Detectors return findings;
the runner aggregates and ranks them.
"""

from posthog.management.migration_profiling.dead_code.models import Confidence, Finding
from posthog.management.migration_profiling.dead_code.runner import DEFAULT_DETECTORS, run_detectors

__all__ = ["Confidence", "Finding", "DEFAULT_DETECTORS", "run_detectors"]
