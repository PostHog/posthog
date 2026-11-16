# Alert destination delivery

Insight alert **Test delivery** sends a synthetic `$insight_alert_firing` event when the alert has an active HogFunction destination.
The destination count includes every template and custom HogFunctions without a template.
Destinations must belong to the alert's project, reference its `alert_id`, listen for an allowed alert event, and be enabled and not deleted.
Only `internal_destination` functions with the `internal-events` filter source receive these events and count toward delivery.
The `alert_id` binding must be a string with the `exact` operator, or no operator for legacy filters.
Counts describe configured destinations; the consumer evaluates additional property filters when it handles the event.

Delivery receipts include these destinations when an alert firing is queued successfully.
A receipt records acceptance of the alert event for delivery, before the consumer evaluates each destination's filters or executes its function.
Unrecognized templates have a destination name and ID but no destination type.

The built-in destination settings only manage templates declared in `SPEC_BY_TEMPLATE_ID`.
That list controls which settings PostHog can read and edit; it does not limit test delivery or receipts.
