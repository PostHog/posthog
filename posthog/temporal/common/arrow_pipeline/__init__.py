"""Destination-agnostic primitives to move Arrow record batches from a producer to a destination.

Batch exports and warehouse sources both use these modules. Keep them free of product-specific
knowledge: callers pass column names, control columns and metric hooks as arguments.
"""
