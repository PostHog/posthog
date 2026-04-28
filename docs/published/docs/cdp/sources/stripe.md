---
title: Linking Stripe as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Stripe
---

The Stripe connector syncs your Stripe data into PostHog, including charges, customers, invoices, products, subscriptions, and more.

## Choosing a sync mode

Stripe tables can be synced in one of three modes, and the one you pick has a big impact on cost, freshness, and correctness. We **strongly recommend using webhook syncs** for any Stripe source you care about keeping accurate:

- **Webhook sync (recommended).** Stripe pushes events to PostHog in real time, so inserts, updates, and deletes all land within seconds. This is the only mode that reliably captures mutations to existing rows, and because PostHog only ingests what Stripe sends you, it's also the cheapest to run on an ongoing basis. See [Setting up webhooks for real-time syncing](#setting-up-webhooks-for-real-time-syncing) below.
- **Append-only (incremental) sync.** PostHog periodically asks Stripe for new rows using Stripe's `created` cursor. This is cheap, but the Stripe API does not expose an "updated since" filter for most resources, so any change to an existing row – a subscription being cancelled, an invoice being marked paid, a customer's email being corrected – is silently missed. Fine for append-only tables you never mutate, dangerous for anything else.
- **Full refresh sync.** PostHog re-downloads every row every sync. This is the only non-webhook mode that will eventually reflect updates, but it's expensive on both sides (lots of Stripe API calls, lots of warehouse writes) and the larger your Stripe account gets, the slower and more costly it becomes. Treat it as a fallback, not a default.

If you only take one thing from this page: connect with a restricted API key (with **Write** on **Webhook**) or OAuth and turn on webhook syncing as soon as your source is created.

## Adding a data source

1. In PostHog, go to the [Data pipeline page](https://app.posthog.com/data-management/sources) and select the **Sources** tab.
2. Click **+ New source** and select Stripe by clicking the **Link** button.
3. Choose your authentication method:

### Option 1: Restricted API key (recommended)

1. Select **Restricted API key** as the authentication type.
2. Head to your Stripe dashboard > **Developers** > **API keys**, under **Restricted keys**, click [+ Create a restricted key](https://dashboard.stripe.com/apikeys/create). You need to give your API key the following permissions:

| Resource Type | Required Permissions                                                                                                                                     |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Core          | **Read** on Balance transaction sources, Charges and refunds, Customers, Disputes, Payment methods, Payouts, Products                                    |
| Billing       | **Read** on Credit notes, Invoices, Prices, Subscriptions                                                                                                |
| Connect       | Click **Read** in the **Connect** header                                                                                                                 |
| Webhooks      | **Write** on Webhooks (so PostHog can create the real-time sync webhook for you – see [Setting up webhooks](#setting-up-webhooks-for-real-time-syncing)) |

If you aren't concerned with giving us more permissions than necessary, you can also simply click **Read** on the **Core**, **Billing**, and **Connect** headers, plus **Write** on **Webhooks**, to give us the necessary permissions.

The **Webhooks** write permission is only required if you want PostHog to set up real-time syncing automatically. If you skip it, everything else still works – you'll just need to [create the webhook manually](#creating-the-webhook-manually-in-stripe) later if you decide to enable real-time syncing.

If your Stripe account is in a language other than English, we suggest you update it to English before following the steps above to guarantee the correct permissions are set.

3. Paste your API key into PostHog.
4. _Optional:_ Add your Stripe Account ID. You can find it by going to **Settings** > **Business**, selecting the [Account details](https://dashboard.stripe.com/settings/account) tab, and clicking your **Account ID** or pressing `⌘` + `I` to copy your ID.
5. _Optional:_ Add a prefix to your table names.
6. Click **Next**.

### Option 2: OAuth connection

1. Select **OAuth connection** as the authentication type.
2. Click the **Connect** button and follow the prompts to authorize PostHog with your Stripe account.
3. _Optional:_ Add your Stripe Account ID. You can find it by going to **Settings** > **Business**, selecting the [Account details](https://dashboard.stripe.com/settings/account) tab, and clicking your **Account ID** or pressing `⌘` + `I` to copy your ID.
4. _Optional:_ Add a prefix to your table names.
5. Click **Next**.

> For Stripe tables, incremental (append-only) syncs only sync new records and don't update existing ones – this is a limitation of the Stripe API, not PostHog. Full refresh syncs do pick up changes but get expensive fast as your Stripe account grows. We strongly recommend [setting up webhooks](#setting-up-webhooks-for-real-time-syncing) for real-time, change-aware syncing instead.

The data warehouse then starts syncing your Stripe data. You can see details and progress in the [data pipeline sources tab](https://app.posthog.com/data-management/sources).

## Setting up webhooks for real-time syncing

Webhook syncing is the mode we recommend for almost every Stripe source. Without it, you're choosing between append-only syncs (which silently miss updates to existing rows because Stripe's API doesn't expose an "updated since" filter) and full refresh syncs (which work but get expensive as your account grows). Webhooks avoid both problems: Stripe pushes every create, update, and delete to PostHog in real time, and PostHog only ingests what actually changed.

### Creating a webhook

1. Go to your Stripe source in the [data pipeline sources tab](https://app.posthog.com/data-management/sources).
2. Click the **Webhook** tab.
3. Click **Create webhook**.

PostHog then calls the Stripe API on your behalf to create and register a webhook endpoint pointing at PostHog, subscribed to the events needed for the tables you're syncing. Once it's set up, the **Webhook** tab shows both PostHog's internal status and the Stripe-side webhook status so you can confirm events are flowing.

If creation succeeds, you don't need to do anything else – the signing secret is stored automatically and PostHog starts ingesting events immediately.

### Updating your restricted API key permissions

If you connected with OAuth, PostHog already has the permissions it needs and you can skip this section.

If you connected with a restricted API key, PostHog can only create the webhook automatically if that key has **Write** access to **Webhooks**. The default read-only permissions listed above are not enough. If automatic creation fails with a permissions or `403` error, update your key:

1. Head to your Stripe dashboard > **Developers** > **API keys**.
2. Find the restricted key you gave to PostHog under **Restricted keys** and click it, then click **Edit key**. (If your key is locked, you'll need to create a new restricted key with the same read permissions plus the webhook write permission below, and paste the new key into your PostHog source configuration.)
3. Under **Webhooks**, change the permission from **None** to **Write**.
4. Save the key.
5. Back in PostHog, return to the **Webhook** tab on your Stripe source and click **Create webhook** again.

We strongly recommend going this route rather than creating the webhook manually – PostHog will pick exactly the right set of events for the tables you're syncing, keep the signing secret in sync, and clean the webhook up if you remove the source later.

### Creating the webhook manually in Stripe

If you'd rather not grant write access to webhooks, you can create the webhook yourself in the Stripe dashboard. PostHog will detect and use it automatically once the signing secret is provided.

1. In PostHog, go to the **Webhook** tab on your Stripe source and copy the **webhook URL** shown there. You'll paste this into Stripe in the next step.
2. Open your [Stripe Dashboard > Developers > Webhooks](https://dashboard.stripe.com/webhooks) and click **Add endpoint**.
3. Paste the PostHog webhook URL into the **Endpoint URL** field.
4. Under **Events to send**, select the events you want Stripe to forward (see below).
5. Click **Add endpoint**.
6. On the new webhook's details page, reveal and copy the **Signing secret** (it starts with `whsec_`).
7. Back in PostHog, paste the signing secret into the **Signing secret** field on the **Webhook** tab and save. PostHog uses this to verify that incoming events really came from Stripe.

#### Which events should you send?

We recommend **selecting all events** when creating the webhook manually. It's the simplest option, it guarantees you won't miss updates to any table you decide to sync later, and Stripe will happily deliver them – PostHog ignores any event it doesn't have a matching table for.

If you'd rather scope the webhook down to just the resources you're syncing, select every event under the prefixes that match your enabled tables:

| PostHog table              | Stripe event prefix       |
| -------------------------- | ------------------------- |
| Account                    | `account.*`               |
| BalanceTransaction         | `transfer.*`              |
| Charge                     | `charge.*`                |
| CreditNote                 | `credit_note.*`           |
| Customer                   | `customer.*`              |
| CustomerBalanceTransaction | `billing.*`               |
| CustomerPaymentMethod      | `payment_method.*`        |
| Dispute                    | `dispute.*`               |
| Invoice                    | `invoice.*`               |
| InvoiceItem                | `invoiceitem.*`           |
| Payout                     | `payout.*`                |
| Price                      | `price.*`                 |
| Product                    | `product.*`               |
| Refund                     | `refund.*`                |
| Subscription               | `customer.subscription.*` |

Narrowing events down means you'll need to revisit the webhook any time you enable a new table, which is why we still recommend **All events** unless you have a specific reason not to.
