# Alert destination delivery

Insight alert **Test delivery** sends a synthetic `$insight_alert_firing` event when the alert has an active HogFunction destination.
The destination count includes every template and custom HogFunctions without a template.
Destinations must belong to the alert's project, reference its `alert_id`, listen for an allowed alert event, and be enabled and not deleted.

Delivery receipts include these destinations when an alert firing is queued successfully.
A receipt records acceptance for delivery, not the destination's eventual execution result.
Unrecognized templates have a destination name and ID but no destination type.

The built-in destination settings only manage templates declared in `SPEC_BY_TEMPLATE_ID`.
That list controls which settings PostHog can read and edit; it does not limit test delivery or receipts.
