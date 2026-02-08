"""URL configuration for Conversations widget API."""

from django.urls import path

from .widget import WidgetMarkReadView, WidgetMessagesView, WidgetMessageView, WidgetTicketsView

urlpatterns = [
    path("v1/widget/message", WidgetMessageView.as_view(), name="widget-message-v1"),
    path("v1/widget/messages/<uuid:ticket_id>", WidgetMessagesView.as_view(), name="widget-messages-v1"),
    path("v1/widget/messages/<uuid:ticket_id>/read", WidgetMarkReadView.as_view(), name="widget-mark-read-v1"),
    path("v1/widget/tickets", WidgetTicketsView.as_view(), name="widget-tickets-v1"),
]
