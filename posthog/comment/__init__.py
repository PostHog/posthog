"""Cross-channel logic shared by anything that mirrors comment threads to external surfaces.

Sits alongside the ``posthog.models.comment`` data layer: this package holds the
channel-agnostic content conversion and Slack identity helpers reused by the
conversations (support) product and core discussions.
"""
