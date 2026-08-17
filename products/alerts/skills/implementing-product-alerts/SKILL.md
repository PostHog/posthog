---
name: implementing-product-alerts
description: >
  Implements alerting for a PostHog product, including alert events, notification destinations, and alert APIs.
  Use when adding a new product alert type, sharing alert-destination infrastructure, or changing ownership and
  authorization of alert notifications. Covers compatibility with existing alert products and generic HogFunction clients.
---

# Implementing product alerts

Use this skill before adding an alert product or changing shared alert-destination behavior.

## Map every surface before adding a guard

Identify all producers, consumers, and management routes for the event or destination shape:

- Product-specific create, list, update, delete, and test-delivery APIs.
- Generic APIs and UIs that create or manage the same underlying records.
- Existing alert products that share event naming, destination templates, or HogFunction queries.
- Background workers and consumers that interpret the events.

Search by exact event names, template IDs, model types, and regex or prefix matches. A broad rule that is correct for
the new product can still capture an older product that uses the generic path.

## Choose an ownership boundary deliberately

New alert products should own their destination lifecycle through product APIs. Those APIs must provide every operation
their UI needs, including listing, creation, deletion, and test delivery, before generic access is restricted.

When a legacy product still uses a generic API, preserve its behavior with a narrow compatibility rule until it migrates.
Do not treat a naming convention as proof that every matching event already uses the new ownership model.

For organization-scoped alerts such as billing alerts, verify that destinations cannot be read or modified by users who
only have project-level access. Check the full path from destination creation through the generic API, query filtering,
and event consumption.

## Test the boundary through each supported surface

Add focused public-interface tests that prove:

- The new product can create and manage its destinations through its owned API.
- Existing products that intentionally use the generic path still create, list, update, and delete their destinations.
- The generic path rejects only products that have fully migrated to product-owned APIs.
- Event filters, template IDs, and query filters agree on which destinations are protected.

Use one regression test per distinct surface. Test the real request path instead of only testing the event-name matcher.

## Migration checklist

Before restricting the generic path:

1. Inventory all matching events and existing clients.
2. Add product-owned APIs and generated clients for every required lifecycle operation.
3. Migrate each client and verify existing destinations remain visible and removable.
4. Add compatibility tests for any product that cannot migrate in the same change.
5. Only then narrow generic listing, retrieval, mutation, and creation.

## Review checklist

- Does a regex, prefix, or shared template match more products than the one being changed?
- Does every UI call the API that the new authorization guard permits?
- Can authorized users still find and remove destinations created before the change?
- Are project and organization authorization rules consistent at create, read, update, delete, and dispatch time?
- Do tests include one legacy or sibling product, not only the new product?
