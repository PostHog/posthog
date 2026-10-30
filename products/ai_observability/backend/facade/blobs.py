"""Facade re-export for offloaded AI blobs.

Isolated from ``facade/api.py``, which imports the clustering workflows, so the eval workers can read blobs without an
import cycle.
"""

from products.ai_observability.backend.ai_blobs import BlobPointer

__all__ = ["BlobPointer"]
