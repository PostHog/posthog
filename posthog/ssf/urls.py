from django.urls import path

from posthog.ssf.views import (
    SSFDiscoveryView,
    SSFJWKSView,
    SSFPollView,
    SSFReceiverView,
    SSFStatusView,
    SSFStreamView,
    SSFSubjectView,
    SSFVerificationView,
)

urlpatterns = [
    path(".well-known/ssf-configuration/<uuid:organization_id>", SSFDiscoveryView.as_view(), name="ssf-discovery"),
    path("ssf/<uuid:organization_id>/jwks.json", SSFJWKSView.as_view(), name="ssf-jwks"),
    path("ssf/<uuid:organization_id>/stream", SSFStreamView.as_view(), name="ssf-stream"),
    path("ssf/<uuid:organization_id>/status", SSFStatusView.as_view(), name="ssf-status"),
    path("ssf/<uuid:organization_id>/subjects:add", SSFSubjectView.as_view(), name="ssf-add-subject"),
    path("ssf/<uuid:organization_id>/subjects:remove", SSFSubjectView.as_view(remove=True), name="ssf-remove-subject"),
    path("ssf/<uuid:organization_id>/verify", SSFVerificationView.as_view(), name="ssf-verify"),
    path("ssf/<uuid:organization_id>/poll/<uuid:stream_id>", SSFPollView.as_view(), name="ssf-poll"),
    path("ssf/<uuid:organization_id>/events", SSFReceiverView.as_view(), name="ssf-events"),
    path("ssf/<uuid:organization_id>/events/<uuid:stream_id>", SSFReceiverView.as_view(), name="ssf-stream-events"),
]
