"""
Facade for apm.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.

So far the only thing consuming products need from APM is whether it is switched
on for a given team, so that is all this exposes for now.
"""

from products.apm.backend.feature_flags import is_apm_enabled

__all__ = ["is_apm_enabled"]
