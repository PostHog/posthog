"""URL configuration for Conversations widget API."""

from django.urls import path

from .widget import WidgetMessagesView, WidgetMessageView, WidgetTicketsView

urlpatterns = [
    path("widget/message", WidgetMessageView.as_view(), name="widget-message"),
    path("widget/messages/<uuid:ticket_id>", WidgetMessagesView.as_view(), name="widget-messages"),
    path("widget/tickets", WidgetTicketsView.as_view(), name="widget-tickets"),
]
