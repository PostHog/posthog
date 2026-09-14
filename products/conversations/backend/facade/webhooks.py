"""Conversations-owned handling of the inbound webhooks it consumes."""

from products.conversations.backend.api.github_events import dispatch_github_event

__all__ = ["dispatch_github_event"]
