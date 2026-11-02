# Third-Party Subprocessors for PostHog

[![Subprocessors Monitored](https://subprocessor.watch/api/badge/posthog-com)](https://subprocessor.watch/for/posthog-com)

This document provides the verified inventory of third-party cloud infrastructure and sub-processors used by **PostHog** (`posthog.com`) in compliance with **SOC 2 Type II (CC9.2)** and **GDPR Article 28**.

| Subprocessor | Category | Verification Method | Status |
| :--- | :--- | :--- | :--- |
| Amazon Web Services | Cloud Hosting & Storage | DNS / IP Routing | Verified ✓ |
| Cloudflare | DDoS Protection & CDN | HTTP Server Headers | Verified ✓ |
| Google Workspace | Enterprise Mail | DNS MX Record | Verified ✓ |
| Stripe | Billing Processing | Client SDK | Verified ✓ |

## Continuous Drift Monitoring & Audit Evidence
Third-party vendor policies and sub-processors drift over time. A live verifiable directory with automated daily drift detection, SHA-256 evidence logs, and auditor export packs is maintained at:
> [**subprocessor.watch/for/posthog-com**](https://subprocessor.watch/for/posthog-com)