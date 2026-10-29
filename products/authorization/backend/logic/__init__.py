"""Internals for authorization. Only facade/api.py calls this package.

The implementation lands here in small steps:
- an OpenFGA client, and the bootstrap of its store and authorization model,
- the authorization model sources, which define the relations and permissions of each resource type,
- the projection that writes each organization's members, roles, access rules and share links as relationships,
- the checks and object lists that answer the facade,
- the rollout that moves each organization from the access control rules to these checks.

Nothing outside this product calls the facade until the rollout is in place.
"""
