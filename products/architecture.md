# Modular Architecture & Isolated Testing

## Purpose

This document defines the future architectural direction for our Django monolith, focusing on:

- Establishing a clear, Django-friendly **folder structure** for modular boundaries
- Using **dataclass-based DTOs** as internal module contracts
- Introducing **facades** as the only public API surface for modules
- Enforcing **isolation** between modules to avoid accidental cross-app leaks
- Enabling **selective testing** via Turbo (task caching) and tach (import boundary enforcement)
- Providing guidance for developers unfamiliar with modern modular-monolith patterns

This is a forward-looking design document, not a migration guide.

# 1. Why Modularization?

As the codebase grows, running all tests for every change becomes expensive. Our goal:

- **Reduce CI time** via selective testing
- **Make module boundaries explicit**
- **Prevent accidental cross-app imports**
- **Preserve developer velocity as the system grows**

Turbo provides task-level caching so that:

- Only tests affected by a change run
- Contract files (DTOs, domain types) determine whether downstream products need retesting

tach enforces Python import boundaries at the module level, ensuring dependencies are explicitly declared in `tach.toml`.

To benefit from selective testing, we must introduce architectural boundaries inside the Django monolith.

# 2. Turbo + tach (Initial Scope: Single App)

We will begin by wiring up **one app** to:

- Validate the folder structure
- Test contract-based selective testing with Turbo
- Verify import boundary enforcement with tach
- Build the foundation for incremental test selection

Focus:

- One app = one Turbo package with `backend:test` and `backend:contract-check` tasks
- Facade (`api/api.py`) will define the **public interface**
- Internal files will be private implementation details
- Presentation layer (DRF) will sit above the API but remain outside the contract surface initially

Eventually this grows into:

- A dependency graph across apps via contract inputs
- True selective test execution

But this document is about foundational structure, not full rollout.

# 3. Folder Structure (Django-Friendly, Modular-Monolith Ready)

Each Django app adopts the following structure:

```text
myapp/
  backend/
    __init__.py
    apps.py
    models.py          # Django ORM only
    domain_types.py    # Enums / domain constants
    logic.py           # Business / domain logic

    tasks/
      __init__.py
      tasks.py         # Celery entrypoints (call facade)
      schedules.py     # Celery beat / periodic config (optional)

    api/
      __init__.py
      api.py           # Facade (public API for other backend modules)
      dtos.py          # DTOs used by facade

    presentation/
      __init__.py
      serializers.py   # DRF serializers (DTO <-> JSON)
      views.py         # DRF views
      urls.py          # HTTP routing

    tests/
      test_models.py   # Unit: model tests
      test_logic.py    # Unit: domain logic tests
      test_api.py      # Unit: facade tests
      test_presentation.py  # Integration: DRF tests
      test_tasks.py    # Integration: Celery tests
```

### Why this layout?

- Matches Django conventions -> low friction
- Keeps business logic separate from HTTP concerns
- Keeps app root clean
- Provides an explicit, enforced boundary (`api/`)
- Scales naturally with contract-based selective testing

For the broader monorepo structure (products, services, platform), see [monorepo-layout.md](/docs/internal/monorepo-layout.md).

# 4. DTOs as Dataclasses

DTOs are **stable, framework-free Python dataclasses**.

### Characteristics:

- No Django imports
- Immutable (`frozen=True`)
- Small, hashable, stable contract surface
- Serve as internal contracts
- Used by facades as inputs/outputs

### Example

```python
@dataclass(frozen=True)
class Artifact:
    id: UUID
    project_id: int
    content_hash: str
    storage_path: str
    width: int
    height: int
    size_bytes: int
    created_at: datetime
```

DTOs **should not depend on**:

- Django models
- DRF serializers
- Request objects

If a DTO's input and output shapes are identical -> reuse the same dataclass.

# 5. Facades: The Public API Surface

Each app exposes a single structured API via `backend/api/api.py`.

This is the **only** module other apps are allowed to import.

### Responsibilities

- Accept DTOs as input parameters
- Call domain logic (`logic.py`)
- Convert Django models -> DTOs
- Enforce transactions where needed
- Remain thin and stable

### Anti-responsibilities

**Do NOT:**

- Implement business logic
- Import DRF, HTTP, serializers
- Expose Django models
- Return ORM instances or QuerySets
- Leak internal implementation details

### Example facade method

```python
class ArtifactAPI:
    @staticmethod
    def create(params: CreateArtifact) -> Artifact:
        instance = logic.create_artifact(params)
        return Artifact.from_model(instance)
```

### Why explicit mappers?

Facades convert ORM models to DTOs via mapper functions. These look repetitive when fields align 1:1:

```python
def _to_artifact(artifact, project_id: UUID) -> dtos.Artifact:
    return dtos.Artifact(
        id=artifact.id,
        content_hash=artifact.content_hash,
        # ... more fields
    )
```

The value isn't the copying--it's having **one place** where "internal" becomes "external contract":

1. **Explicit contract** - DTOs define exactly what callers receive. Internal fields don't accidentally leak.
2. **Transformation point** - Add computed fields, flatten relations, rename for API consistency.
3. **Drift absorption** - When models and DTOs diverge, mappers handle it cleanly instead of changes leaking everywhere.

The alternative--returning ORM objects--works until it doesn't, then you're retrofitting isolation under pressure.

# 6. Domain Logic (backend/logic.py)

Business logic lives here.

Examples:

- Deduplication rules
- Domain invariants
- Cross-field validations
- Idempotency

### Why?

- Facades must stay thin and stable
- Presentation should not contain domain rules
- DTOs remain pure data
- Logic is internal implementation--changes here don't affect other products' tests

This is the **heart** of the module.

# 7. Presentation Layer (DRF)

Located in `backend/presentation/`.

Responsibilities:

- Validate incoming JSON (via DRF serializers)
- Convert incoming JSON -> DTOs
- Call facade methods
- Convert DTOs -> JSON responses
- No business logic

### Why not mix with domain or facade?

- Keeps HTTP concerns decoupled
- Allows reusing domain logic for:
  - async tasks
  - CLI
  - future services

### Serializer generation

Serializers for outgoing responses can be auto-generated from DTOs.

### Don't API views leak implementation?

No, because:

- Views only call facades
- Facades return DTOs, not models

So it's the responsibility of the API developer to keep logic and implementation separate and only use facades. This way, the presentation layer remains decoupled from internal details. We can still run isolated tests on the domain logic while being sure that when our facade has not changed, anything outside the module is unaffected.

# 8. Isolation, No-Leak Rules & Django Foreign Key Considerations (for Developers)

To keep architecture clean, developers must follow:

### Forbidden

- One app importing another app's `models.py`
- Using a model across boundaries
- Importing anything from `backend/logic.py` outside the app
- Importing views/serializers from another app
- Returning ORM objects from facades
- Calling internal functions of another module

### Allowed

- Importing `myapp.backend.api` from another module
- Returning DTOs from facades
- Calling domain logic only from inside the same app
- Letting presentation call facade functions

### Special Note on Django Foreign Keys

Django allows establishing `ForeignKey` relationships between models across apps. This is still allowed, but with important caveats. ForeignKey relations create **implicit reverse dependencies**, even if you never use them.

Example:

```python
# visual_review/backend/models.py
project = models.ForeignKey(Project, ...)
```

Even if your app never calls `Project`, Django will auto-generate:

- reverse relations (e.g. `project.visualreview_set`)
- migration dependencies
- app loading order dependencies

This violates isolation:

- Reverse relations leak internal implementation details
- Creates hidden dependencies across apps
- Makes selective testing harder
- Makes boundaries unclear to developers

### Rule:

**A Django app may have ForeignKeys _to_ external apps (unless those are also strictly isolated), but other apps must not reference models _inside_ this app.**

If you need reverse access, use:

- explicit API calls (`OtherAppAPI.list_for_project(project_id)`) rather than ORM traversal
- explicit DTO returns instead of model access

This preserves clean boundaries.

This prevents:

- Hidden dependencies
- Coupling across apps
- Test explosion
- Data-layer leaks

# 9. Turbo Tasks & Contract-Based Testing

Each product is a Turborepo package with tasks defined in its `package.json`:

## Contract files vs. implementation files

Turbo uses file-based inputs to determine cache validity. The key distinction:

**Contract inputs** (used by `backend:contract-check`):

- `backend/api/dtos.py` - DTO definitions
- `backend/domain_types.py` - Enums, domain constants

**Implementation inputs** (used by `backend:test`):

- All `backend/**/*.py` files

Other products depend on a product's **contract files only**. When contract files haven't changed, downstream products don't need retesting.

**Import boundaries** are enforced by tach via `tach.toml`. This ensures products don't accidentally import each other's internals, which would break the contract-based isolation model.

**Dependency rules for contract files (keep them pure):**

- No Django imports (`from django.*`)
- No DRF imports (`from rest_framework.*`)
- Use stdlib for errors, not `django.core.exceptions`
- No `DTO.from_model()` methods - put conversion in implementation code

## How selective testing works

```text
other_product tests
       | depends on
visual_review contracts  (dtos.py, domain_types.py)
       | does NOT depend on
visual_review impl       (logic.py, models.py)
```

**Scenario: Change `visual_review/logic.py`**

- `visual_review backend:test` -> reruns (impl files changed)
- `visual_review backend:contract-check` -> cache hit (contract files unchanged)
- `other_product backend:test` -> skipped (depends only on contracts, which didn't change)

## CI commands

```bash
# Run all product tests
pnpm turbo run backend:test

# Run specific product tests
pnpm turbo run backend:test --filter=@posthog/products-visual_review

# Run contract checks
pnpm turbo run backend:contract-check
```

# 10. Summary

This document outlines the **future direction** of our codebase:

- Django-idiomatic layout with modular boundaries
- Dataclass DTOs as stable contracts
- Thin facades as the only public interface
- Domain logic isolated and testable
- DRF presentation decoupled from core logic
- Turbo for task caching and selective test execution
- tach for Python import boundary enforcement

This architecture:

- Reduces coupling
- Enables selective testing
- Prepares us for monorepo-scale tooling
- Keeps the system maintainable as we grow
