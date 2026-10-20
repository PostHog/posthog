# Test cases for the api-route-path-underscore-in-products rule.
# ruff: noqa


api_urlpatterns = [
    # ruleid: api-route-path-underscore-in-products
    re_path(r"^v1/email/set-trusted-relay/?$", EmailSetTrustedRelayView.as_view(), name="email-set-trusted-relay"),
    # ruleid: api-route-path-underscore-in-products
    path("count-accounts/", csrf_exempt(CountAccountsView.as_view())),
    # ok: api-route-path-underscore-in-products
    re_path(r"^v1/email/set_trusted_relay/?$", EmailSetTrustedRelayView.as_view(), name="email-set-trusted-relay"),
    # ok: api-route-path-underscore-in-products
    path("external/ticket/<uuid:ticket_id>", ExternalTicketView.as_view(), name="external-ticket"),
]

webhook_urlpatterns = [
    # ok: api-route-path-underscore-in-products
    path("ses-events", SesEventsView.as_view()),
    # ok: api-route-path-underscore-in-products
    re_path(r"^vapi-webhook/?$", VapiWebhookView.as_view()),
]

webhook_urlpatterns: list[URLPattern] = [
    # ok: api-route-path-underscore-in-products
    path("annotated-events", SesEventsView.as_view()),
]
