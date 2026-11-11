"""Internals for authorization. Only facade/api.py, the request middleware and the app config call this package.

Until the rollout, `legacy.py` answers the facade with the current access control rules, so a call
site that moves to the facade keeps its behavior. The OpenFGA implementation lands here in small steps:
- an OpenFGA client, and the bootstrap of its store and authorization model,
- the authorization model sources, which define the relations and permissions of each resource type,
- the projection that writes each organization's members, roles, access rules and share links as relationships,
- the checks and object lists that answer the facade,
- the rollout that moves each organization from the access control rules to these checks.
"""
