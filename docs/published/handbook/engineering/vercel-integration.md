---
title: Vercel integration
sidebar: Handbook
showTitle: true
---

A reference for understanding how the PostHog + Vercel Marketplace integration works end-to-end. Covers installation, billing, usage reporting, feature flag sync, SSO, and uninstall.

### Key concepts

Before diving in, a few PostHog data model basics:

- **Organization** contains one or more **Teams** (called "Projects" in the UI)
- **`OrganizationIntegration`** stores Vercel credentials (access tokens, installation ID) scoped to the org. One per Vercel installation.
- **`Integration`** is a per-team/project record for resource-level config (environment variables, product settings). Created when a Vercel resource is provisioned for a specific project.
- **`BillingManager`** (`ee/billing/billing_manager.py`) is the intermediary PostHog uses to talk to the Billing service. It handles license validation, org syncing, and the actual HTTP calls.

---

## Table of Contents

1. [High-level architecture](#1-high-level-architecture)
2. [Installation flows](#2-installation-flows)
3. [Billing & subscriptions](#3-billing--subscriptions)
4. [Usage reporting](#4-usage-reporting)
5. [Invoice lifecycle](#5-invoice-lifecycle)
6. [Payment failure & collections](#6-payment-failure--collections)
7. [Feature flag & experiment sync](#7-feature-flag--experiment-sync)
8. [SSO (single sign-on)](#8-sso-single-sign-on)
9. [Uninstall flow](#9-uninstall-flow)
10. [Monitoring](#10-monitoring)
11. [Contacting Vercel support](#11-contacting-vercel-support)
12. [Key files reference](#12-key-files-reference)

---

## 1. High-level architecture

```mermaid
graph LR
    Vercel["Vercel\nMarketplace + API"]
    PostHog["PostHog\n(posthog repo)"]
    Billing["Billing Service\n(billing repo)"]
    Stripe["Stripe"]

    Vercel -->|"Install / Uninstall\nInvoice paid webhook"| PostHog
    PostHog -->|"Sync feature flags\nSSO token exchange"| Vercel
    PostHog -->|"Create subscription\nCancel subscription"| Billing
    Billing -->|"Submit usage daily\nSubmit invoices"| Vercel
    Billing -->|"Create subscription\nGenerate invoices"| Stripe
    Stripe -->|"invoice.finalized\nwebhook"| Billing
```

The PostHog repo handles installation, SSO, feature flag sync, and webhooks from Vercel. The Billing repo handles subscription management, usage reporting to Vercel, and invoice submission. They communicate via internal HTTP APIs through `BillingManager`.

---

## 2. Installation flows

There are two ways a customer gets the Vercel integration:

### A. Marketplace install (new customer)

A brand new user clicks "Add" in the Vercel Marketplace. PostHog creates everything from scratch.

```mermaid
sequenceDiagram
    actor User
    participant VM as Vercel Marketplace
    participant PH as PostHog
    participant BM as BillingManager
    participant Billing as Billing Service
    participant Stripe

    User->>VM: Click "Add Integration"
    VM->>PH: PUT /api/vercel/v1/installations/{id}
    Note right of PH: installation credentials, user info

    PH->>PH: Create Organization (if new)
    PH->>PH: Create Team (Project)
    PH->>PH: Create OrganizationIntegration

    PH->>BM: authorize(billing_provider="vercel")
    BM->>Billing: POST /api/activate/authorize
    Billing->>Billing: Set customer.billing_provider = "vercel"
    Billing->>Stripe: Create subscription
    Note right of Stripe: collection_method=send_invoice\nmetadata.billing_provider=vercel
    Stripe-->>Billing: subscription_id
    Billing-->>BM: {success: true, subscription_id}

    PH-->>VM: Installation complete
    VM-->>User: Redirect to PostHog
```

**Key endpoint:** `PUT /api/vercel/v1/installations/{installation_id}` in `ee/api/vercel/vercel_installation.py`

### B. Connectable account (link existing PostHog org)

An existing PostHog customer links their org via OAuth. Billing stays with PostHog (no `billing_provider` change).

```mermaid
sequenceDiagram
    actor User
    participant VM as Vercel Marketplace
    participant PH as PostHog

    User->>VM: Click "Link Existing Account"
    VM->>PH: GET /connect/vercel/callback (OAuth code)
    PH->>PH: Exchange code for access token
    PH->>PH: Store session in cache (10 min TTL)

    PH-->>User: Show org selection page
    User->>PH: Select org, POST /api/vercel/connect/complete
    PH->>PH: Validate session + cookie
    PH->>PH: Create OrganizationIntegration (type="connectable")
    PH-->>User: Redirect to next_url
```

**Key endpoints:**

- `GET /connect/vercel/callback` - OAuth callback (`ee/api/vercel/vercel_connect.py`)
- `GET /api/vercel/connect/session` - Available orgs for linking
- `POST /api/vercel/connect/complete` - Finalize the link

**Note:** Connectable installs do NOT call the billing service. The customer keeps their existing PostHog billing. On uninstall, the `OrganizationIntegration` record is simply deleted with no billing side effects.

---

## 3. Billing & subscriptions

### How Vercel billing differs

Vercel acts as the **payment collector**. PostHog still uses Stripe to track usage and generate invoices, but Stripe never charges the customer directly.

```mermaid
graph LR
    subgraph Normal PostHog Customer
        A1[Customer] -->|Card on file| A2[Stripe]
        A2 -->|charge_automatically| A3[Invoice paid]
    end

    subgraph Vercel Customer
        B1[Customer] -->|Pays through| B2[Vercel]
        B3[PostHog/Stripe] -->|send_invoice| B4[Invoice created\nstatus: open]
        B3 -->|Submit invoice| B2
        B2 -->|Webhook: invoice paid| B3
        B3 -->|pay out_of_band| B5[Invoice paid]
    end
```

### How Vercel customers differ from regular customers

| Aspect                          | Vercel customer                        | Regular PostHog customer |
| ------------------------------- | -------------------------------------- | ------------------------ |
| **Signs up via**                | Vercel Marketplace                     | posthog.com              |
| **Pays through**                | Vercel                                 | Stripe (card on file)    |
| **Stripe `collection_method`**  | `send_invoice`                         | `charge_automatically`   |
| **`days_until_due`**            | 30                                     | N/A                      |
| **`metadata.billing_provider`** | `"vercel"`                             | Not set                  |
| **Invoice status**              | "open" until Vercel webhook            | "paid" after card charge |
| **Customer email**              | `noreply+vercel-{org_id}@posthog.com`  | Real email               |
| **Communications**              | Vercel handles                         | PostHog sends            |
| **Daily usage**                 | Reported to Vercel + Stripe            | Stripe only              |
| **Invoice submission**          | Submitted to Vercel after finalization | Not needed               |
| **Feature flags**               | Synced to Vercel Experimentation       | PostHog only             |
| **SSO**                         | Via Vercel (`/login/vercel`)           | PostHog login            |
| **Uninstall**                   | Resets to `billing_provider=posthog`   | N/A                      |

### The `billing_provider` field

On the Customer model (`billing/models/customer.py`):

- Default: `"posthog"`
- Set to `"vercel"` during marketplace installation
- Reset to `"posthog"` on uninstall
- Also stored in Stripe subscription metadata (survives provider reset for final invoice handling)

---

## 4. Usage reporting

PostHog reports usage to Vercel daily so it appears in the Vercel dashboard.

```mermaid
sequenceDiagram
    participant Celery as Celery Task\nreport_daily_usage
    participant Usage as submit_usage_to_vercel
    participant Stripe
    participant Vercel as Vercel API

    Celery->>Usage: Trigger (2 min delay after daily report)

    Usage->>Usage: Get latest usage report
    Usage->>Stripe: Invoice.upcoming(subscription_id)
    Stripe-->>Usage: Upcoming invoice with line items

    Usage->>Vercel: POST usage submission
    Note right of Vercel: Payload includes:\n- Period usage (cumulative)\n- Daily usage (today only)\n- Billing line items with pricing
```

### Usage payload structure

```json
{
  "timestamp": "2025-01-15T14:30:00Z",
  "eod": "2025-01-14T23:59:59Z",
  "period": { "start": "...", "end": "..." },
  "billing": [
    {
      "billingPlanId": "price_xxx",
      "name": "Product Analytics",
      "price": "0.000025",
      "quantity": 123456,
      "units": "events",
      "total": "3.09"
    }
  ],
  "usage": [
    {
      "name": "Events",
      "type": "interval",
      "units": "events",
      "dayValue": 456,
      "periodValue": 12345
    }
  ]
}
```

**Task location:** `billing/tasks/usage.py` - `submit_usage_to_vercel()`

---

## 5. Invoice lifecycle

```mermaid
sequenceDiagram
    participant Stripe
    participant Billing as Billing Service
    participant Vercel as Vercel API

    Note over Stripe: End of billing period
    Stripe->>Billing: Webhook: invoice.finalized

    Billing->>Billing: Resolve billing provider\n(3-level fallback)
    Billing->>Billing: Format invoice (VercelFormatter)
    Billing->>Vercel: POST submit invoice
    Note right of Vercel: Includes line items,\ndiscounts, period, memo
    Vercel-->>Billing: {invoiceId: "mi_xxx"}
    Billing->>Billing: Store Vercel invoice ID\nin billing_provider_metadata

    Note over Vercel: Customer pays Vercel
    Vercel->>Billing: POST /api/billing/webhook/billing-provider
    Note right of Billing: {event_type, billing_provider,\nevent_data: {invoiceId}}

    Billing->>Billing: Find invoice by Vercel ID
    Billing->>Stripe: Invoice.pay(paid_out_of_band=True)
    Billing-->>Vercel: {status: "ok"}
```

### Billing provider resolution (`_resolve_billing_provider`)

When an invoice is finalized, the system needs to determine which billing provider it belongs to. This uses a 3-level fallback chain:

1. **`customer.billing_provider`** - the live value on the customer model
2. **`subscription_details.metadata.billing_provider`** - snapshot from Stripe subscription metadata (set at subscription creation time)
3. **`billing_provider_metadata.billing_provider`** - stored on the local Invoice model

This fallback chain is what makes the uninstall flow resilient. After uninstall, `customer.billing_provider` is already reset to `"posthog"`, but the subscription metadata still says `"vercel"`, so the final invoice is still submitted correctly.

### Skipped invoices

Invoices with `billing_reason == "subscription_create"` are silently skipped. These are $0 setup invoices generated when the Stripe subscription is first created. If you're debugging why the "first invoice" never appeared in Vercel, this is why.

### Webhook payload structure

The "invoice paid" webhook from Vercel:

```json
{
  "event_type": "marketplace.invoice.paid",
  "billing_provider": "vercel",
  "event_data": {
    "invoiceId": "mi_xxx"
  }
}
```

### Invoice submission data

```json
{
  "externalId": "in_xxx",
  "invoiceDate": "2024-01-01T00:00:00Z",
  "period": { "start": "...", "end": "..." },
  "items": [
    {
      "billingPlanId": "price_xxx",
      "name": "PostHog - Product Analytics",
      "price": "0.000025",
      "quantity": 1000000,
      "units": "events",
      "total": "25.00"
    }
  ],
  "discounts": [{ "billingPlanId": "discount", "name": "Coupon: SAVE20", "amount": "5.00" }]
}
```

**Key files:**

- `billing/webhooks/stripe.py` - `submit_invoice_to_billing_provider()` (triggered on `invoice.finalized`)
- `billing/billing_providers/clients/vercel_formatter.py` - formats line items, discounts
- `billing/api/billing_provider_webhook.py` - receives "invoice paid" from Vercel

---

## 6. Payment failure & collections

When a Vercel customer's payment fails, Vercel handles the initial retry and dunning communication. PostHog only needs to act after the retry window expires.

```mermaid
sequenceDiagram
    participant Vercel as Vercel
    participant PH as PostHog
    participant Customer

    Note over Vercel: Invoice payment fails
    Vercel->>PH: Webhook: marketplace.invoice.notpaid
    Vercel->>Customer: Payment failure emails (dunning)
    Note over Vercel: 15-day retry window begins

    alt Customer pays during retry
        Vercel->>PH: Webhook: marketplace.invoice.paid
        Note over PH: No action needed
    else Retry window elapses
        Vercel->>PH: Webhook: marketplace.invoice.overdue
        PH->>Vercel: PATCH installation status: "suspended"
        PH->>Customer: Notification (email via Get Account Information)
        Note over PH: Wait at least 15 more days\nbefore any destructive action
    end

    alt Customer pays after suspension
        PH->>Vercel: PATCH installation status: "resumed"
        PH->>PH: Restore service
    end
```

### Webhook events

| Event                         | Fired when                                  | Docs                                                                                     |
| ----------------------------- | ------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `marketplace.invoice.notpaid` | Invoice payment fails                       | [Vercel docs](https://vercel.com/docs/webhooks/webhooks-api#marketplace.invoice.notpaid) |
| `marketplace.invoice.overdue` | 15-day retry window elapses without payment | [Vercel docs](https://vercel.com/docs/webhooks/webhooks-api#marketplace.invoice.overdue) |

During the 15-day retry window, Vercel owns all customer-facing payment failure communication. We do not need to send any dunning emails during that period.

### Recommended response after `overdue`

Once the `marketplace.invoice.overdue` webhook fires:

1. **Suspend the installation** - graceful, recoverable degradation (not data deletion)
2. **Notify the customer** - use the [Get Account Information](https://vercel.com/docs/integrations/create-integration/marketplace-api/reference/vercel/get-account-information) endpoint to get contact info and send an email
3. **Wait at least 15 additional days** before any destructive action (deleting data, removing resources). Degradation alone may prompt payment.

### Suspension API

Suspend an entire installation:

```http
PATCH /v1/installations/:integrationConfigurationId
{ "status": "suspended" }
```

Suspend individual resources:

```http
PATCH /v1/installations/:integrationConfigurationId/resources/:resourceId
{ "status": "suspended" }
```

Add a notification banner (optional, shown in the Vercel dashboard):

```json
{
  "notification": {
    "level": "error",
    "title": "Account suspended",
    "message": "Your invoice is past due. Please update your payment method.",
    "href": "https://your-billing-page.example.com"
  }
}
```

`level` supports `info`, `warn`, or `error`. Send `notification: null` to clear.

To resume after payment, set `{ "status": "resumed" }`. Valid statuses: `ready`, `pending`, `onboarding`, `suspended`, `resumed`, `uninstalled`, `error`.

Suspension status is for **display only** within Vercel. To actually block access, you must also stop serving the customer on the PostHog side.

### Tracking unpaid invoices

Track invoice status via the webhook lifecycle events (`notpaid` -> `overdue` -> `paid`). Alternatively, query the [get-invoice endpoint](https://vercel.com/docs/integrations/create-integration/marketplace-api/reference/vercel/get-invoice) against stored invoice IDs.

---

## 7. Feature flag & experiment sync

PostHog automatically syncs feature flags and experiments to Vercel's experimentation platform via Django signals.

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant PH as PostHog
    participant Signal as Django Signal
    participant Vercel as Vercel API

    Dev->>PH: Create/Update Feature Flag
    PH->>Signal: post_save fired
    Signal->>Signal: Check if org has\nVercel integration
    Signal->>Vercel: POST create/update\nexperimentation item

    Dev->>PH: Delete Feature Flag
    PH->>Signal: post_save (soft delete) or\npost_delete (hard delete)
    Signal->>Vercel: DELETE experimentation item
```

- **Sync on save:** `VercelIntegration.sync_feature_flag_to_vercel()` / `sync_experiment_to_vercel()`
- **Sync on delete:** `VercelIntegration.delete_feature_flag_from_vercel()` / `delete_experiment_from_vercel()`
- **Soft deletes:** The `post_save` handler checks `instance.deleted` and calls the delete method if the flag was soft-deleted. Hard deletes go through `post_delete`.
- **Safety:** Wrapped in `_safe_vercel_sync()` to prevent DB transaction failures
- **Client:** `VercelAPIClient` in `ee/vercel/client.py` with exponential backoff retry

---

## 8. SSO (single sign-on)

Vercel users can SSO into PostHog without a separate login.

```mermaid
sequenceDiagram
    actor User
    participant Vercel
    participant PH as PostHog

    User->>Vercel: Click "Open PostHog"
    Vercel->>PH: GET /login/vercel?code=xxx&state=yyy
    PH->>Vercel: Exchange SSO code for token response
    Vercel-->>PH: Token response (id_token JWT + access_token)
    PH->>PH: Validate id_token JWT, extract user/team claims
    PH->>PH: Find matching OrganizationIntegration
    PH->>PH: Log user in
    PH-->>User: Redirect to dashboard
```

**Endpoints:**

- `GET /login/vercel` - SSO entry point (`ee/api/vercel/vercel_sso.py`)
- `GET /login/vercel/continue` - For already-logged-in users

**Multi-region:** If the resource doesn't exist in the current region (e.g. US), PostHog proactively redirects to the other region (EU). This is a region check, not a failure fallback.

---

## 9. Uninstall flow

There are two uninstall paths depending on how the integration was installed:

### Marketplace uninstall (billing involved)

```mermaid
sequenceDiagram
    actor User
    participant VM as Vercel Marketplace
    participant PH as PostHog
    participant BM as BillingManager
    participant Billing as Billing Service
    participant Stripe

    User->>VM: Uninstall PostHog integration
    VM->>PH: Webhook: integration.configuration-removed\n(HMAC-SHA1 signed)

    PH->>PH: Validate HMAC signature
    PH->>BM: deauthorize(billing_provider="vercel")
    BM->>Billing: POST /api/activate/authorize/uninstall

    Billing->>Billing: Validate billing_provider matches
    Billing->>Billing: Check for unpaid invoices

    alt Has unpaid invoices
        Billing-->>PH: 409 - OPEN_INVOICES
        PH-->>VM: 500 (all billing errors\nreturn generic 500 to Vercel)
    else No unpaid invoices
        Billing->>Stripe: Cancel subscription (invoice_now=True)
        Stripe-->>Billing: Final invoice generated
        Billing->>Billing: Queue final invoice submission\nto Vercel (Celery task with\nbilling_provider passed as arg)
        Billing->>Billing: Reset billing_provider to "posthog"
        Billing-->>BM: {success: true}
        BM-->>PH: success
        PH->>PH: Delete OrganizationIntegration
    end
```

**Critical detail:** The final invoice Celery task receives `billing_provider` as an explicit string argument at queue time (when it's still `"vercel"`). It does NOT read `customer.billing_provider` at execution time. This is why the reset to `"posthog"` doesn't break final invoice submission. As an additional safety net, the [billing provider resolution fallback chain](#billing-provider-resolution-_resolve_billing_provider) also protects against this — even if the Celery argument were lost, the subscription metadata still retains the original billing provider value.

### Connectable uninstall (no billing)

For connectable integrations (linked existing accounts), the webhook handler simply deletes the `OrganizationIntegration` record. No billing service call is made since these customers keep their existing PostHog billing.

**Key files:**

- `ee/api/vercel/vercel_webhooks.py` - Webhook handler
- `ee/vercel/integration.py` - `VercelIntegration.delete_installation()`
- `billing/api/billing.py` - Uninstall endpoint
- `billing/models/customer.py` - `cancel_billing_provider_subscription()`

---

## 10. Monitoring

PostHog dashboard: [Vercel Billing Integration](https://us.posthog.com/project/2/dashboard/1404045) - covers customer integrity, invoice lifecycle, usage reporting, submission gap tracking, and financial reconciliation.

---

## 11. Contacting Vercel support

For integration or billing issues that need Vercel's involvement, post in the shared Slack channel [#posthog-vercel](https://posthog.slack.com/archives/C08LYBQ58N5) with a :ticket: reaction on the message. This flags it for the Vercel team to pick up.

---

## 12. Key files reference

### PostHog repo (`posthog/`)

| File                                         | Purpose                                                                |
| -------------------------------------------- | ---------------------------------------------------------------------- |
| `ee/api/vercel/vercel_installation.py`       | Installation CRUD (`PUT /api/vercel/v1/installations/{id}`)            |
| `ee/api/vercel/vercel_connect.py`            | Connectable account OAuth flow                                         |
| `ee/api/vercel/vercel_sso.py`                | SSO endpoints (`/login/vercel`)                                        |
| `ee/api/vercel/vercel_webhooks.py`           | Webhook handler (`/webhooks/vercel`)                                   |
| `ee/api/vercel/vercel_resource.py`           | Resource management (Vercel projects)                                  |
| `ee/api/vercel/vercel_product.py`            | Product plans                                                          |
| `ee/vercel/client.py`                        | `VercelAPIClient` - HTTP client for Vercel APIs                        |
| `ee/vercel/integration.py`                   | `VercelIntegration` class - core logic (upsert, delete, sync flags)    |
| `ee/billing/billing_manager.py`              | `BillingManager` - intermediary for all billing service calls          |
| `posthog/models/organization_integration.py` | `OrganizationIntegration` model (org-level, stores Vercel credentials) |
| `posthog/models/integration.py`              | `Integration` model (team/project-level resource record)               |

### Billing repo (`billing/`)

| File                                            | Purpose                                                               |
| ----------------------------------------------- | --------------------------------------------------------------------- |
| `api/activate.py`                               | `BillingAuthorizeViewSet` - authorize + deprecated uninstall redirect |
| `api/billing.py`                                | Canonical uninstall endpoint (`/api/billing/uninstall`)               |
| `api/billing_provider_webhook.py`               | Receives "invoice paid" webhook from Vercel                           |
| `billing_providers/clients/vercel.py`           | `VercelClient` - submits usage & invoices to Vercel                   |
| `billing_providers/clients/vercel_api.py`       | Low-level API calls via PostHog proxy                                 |
| `billing_providers/clients/vercel_formatter.py` | Formats invoices/usage for Vercel's API                               |
| `models/customer.py`                            | `billing_provider` field, `cancel_billing_provider_subscription()`    |
| `tasks/usage.py`                                | `submit_usage_to_vercel()` daily task                                 |
| `webhooks/stripe.py`                            | `submit_invoice_to_billing_provider()` on `invoice.finalized`         |
| `constants/billing_provider.py`                 | `BillingProvider` enum, webhook event constants                       |
