EMAIL_RESOURCE_NAME = "email"
PUSH_RESOURCE_NAME = "push"
SMS_RESOURCE_NAME = "sms"
IN_APP_RESOURCE_NAME = "in_app"
SLACK_RESOURCE_NAME = "slack"
WEBHOOK_RESOURCE_NAME = "webhook"
CUSTOMER_RESOURCE_NAME = "customer"

# Maps PostHog resource name -> Customer.io reporting webhook object_type.
# See https://customer.io/docs/journeys/reporting-webhooks/
RESOURCE_TO_CIO_OBJECT_TYPE: dict[str, str] = {
    EMAIL_RESOURCE_NAME: "email",
    PUSH_RESOURCE_NAME: "push",
    SMS_RESOURCE_NAME: "sms",
    IN_APP_RESOURCE_NAME: "in_app",
    SLACK_RESOURCE_NAME: "slack",
    WEBHOOK_RESOURCE_NAME: "webhook",
    CUSTOMER_RESOURCE_NAME: "customer",
}

CIO_ENDPOINTS: tuple[str, ...] = tuple(RESOURCE_TO_CIO_OBJECT_TYPE.keys())
