"""
Contract types for data_catalog.

Frozen dataclasses that define what this product exposes to other products. No Django imports.

v1 has no in-process cross-product consumers: information_schema loaders read the ORM classes via
``facade.models`` and everything else goes over HTTP. Contracts will land here when a Python caller
in another product needs metric/certification data.
"""
