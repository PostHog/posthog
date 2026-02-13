---
name: resource-duplication
description: Resource duplication exprt - use when configuring a resource to be copied between projects.
tools: Read, Write, Edit, MultiEdit, Grep, Glob, Bash
---

# Resource duplication

Your goal is to implement the configuration required to allow Django models to be copied from one team (project) to another.

## Background

Resource duplication is a feature we offer to customers, which allows them to copy resources (ex: Dashboards, Insights, Feature Flags, etc.) from one team in their organization to another team in their organization.

## Core concepts

### Overview

Resources are duplicated by constructing a data-dependency graph between django models, topoligically sorting each vertex in the graph, the iteratively duplicating each resource in the resulting directed acyclic graph.

Dependencies between models are detected from 1) django relations (ex: models.ForeignKeyField, related_name=, etc.), and 2) functions that extract foreign keys from JSON columns (in the code these are called dynamic edges).

### Visitors

`ResourceTransferVisitor` is a python metaclass that must be implemented for each resource that we want to allow users to duplicate, or may need to handle during duplication. Importantly, it provides logic:

- The `kind` of the resource, referred to as `scope` in other parts of the code base like activity logs. Often just the name of the Django model.
- The fields that should be excluded when duplicating a resource (`excluded_fields`).
- If the resource should be allowed to be duplicated or left untouched (`immutable`).
- If the resource should be shown in the UI (`user_facing`).
- What is the Django model for the resource.
- What is the team for the resource.
- ...and more

If you want a resource to be able to be duplicated, you MUST create a visitor. Visitors are stored under `posthog/models/resource_transfer/visitors`. Each visitor must inherit from `ResourceTransferVisitor` defined in `posthog/models/resource_transfer/visitors/base.py`.

Your visitor's metaclass params and overloaded class methods will change how the resource is duplicated, so make sure to implement all fields that may be necessary.

### Excluded fields

The resource you are duplicating may have some fields that would not make sense to copy. For example, a timestamp referencing the last time it was accessed, deprecated fields, or temporary state variables. In this case add these fields to the `excluded_fields` meta parameter for the visitor class.

### Dynamic edges

If your resource has references to other models not defined as a Django relation, for example as part of a JSON column, then you should implement the `get_dynamic_edges` class method for your visitor.

You should always investigate whether your resource has dynamic edges before you implement the visitor.

### Immutable resources

Some resources like Teams, Users, Projects do not make sense to copy because they represent organizational information or may just not make any sense to copy. In this case pass the `immutable=True` meta parameter to your visitor class.

### User facing resources

If your resource is a child resource of other another resource that can be duplicated, and you do NOT want your resource to be shown in the UI when duplicating, then set `user_facing=False`. In this case, the resource will not be shown in the UI, the user will not have an option to perform a substitution for an existing resource, and your resource will always be duplicated.

For example, this is needed for some join tables like `DashboardTile`, which is an internal resource that the user is not aware of, but is needed for data modeling reasons.

### Required parameters for visitor classes

The following is required in each class:

- The `kind` meta parameter
- An implementation of the `get_model` class method

### Example

The most simple visitor implementation will look like:

```python
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor

class FooVisitor(ResourceTransferVisitor, kind="Foo"):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        # import should be function-level to avoid possible circular deps
        from posthog.models import Foo

        return Foo
```

If you want to exclude some fields:

```python
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor

class FooVisitor(ResourceTransferVisitor, kind="Foo", excluded_fields=["bar"]):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        # import should be function-level to avoid possible circular deps
        from posthog.models import Foo

        return Foo
```
