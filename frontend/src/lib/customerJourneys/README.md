# Customer journey telemetry

See the [customer journey telemetry guide](../../../../docs/internal/customer-journey-telemetry.md) for lifecycle rules, measurement contracts, enrollment and reporting limits.

`startCustomerJourney` is the runtime entry point. `createCustomerJourney` holds the independently testable lifecycle, and each product adapter owns its readiness condition and asynchronous generation identity.
