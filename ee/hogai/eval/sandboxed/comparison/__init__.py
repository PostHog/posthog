"""One-off CLI-vs-MCP comparison benchmark (not a persistent eval suite).

Throwaway harness for the blog/team writeup: runs the same neutral tasks against
three arms (posthog-cli binary, MCP tools-mode, MCP exec-mode) and reports tokens,
success, and time per arm. Reuses the sandboxed eval fixtures for setup; emits a
markdown + JSON report rather than scoring into Braintrust. Safe to delete.
"""
