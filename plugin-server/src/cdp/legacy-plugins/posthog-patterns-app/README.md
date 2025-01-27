# PostHog Patterns App

Send PostHog event data to a webhook endpoint in a [patterns.app](https://patterns.app/) graph.

## Installation

- Sign up for a free Patterns account [here](https://www.patterns.app/beta)
- Create a graph in Patterns and add a webhook node in it. ![Patterns Graph Webhook](patterns_graph_webhook.png)
- Copy the webhook URL from the sidebar.
- Install Patterns app from PostHog. Paste the URL in "Patterns Webhook URL" during app configuration.
- [Optional] Set a comma-separated list of allowed event types for sending to Patterns. Example: `$pageview, $pageview`. If empty, all events are sent to Patterns.

## Function

- Ingest data from PostHog to Patterns 
- Sync with other destinations or databases 
- Generate models to measure customer health and churn risk 
- Integrate with other data in Patterns and create a customer data platform 

## We'd love to connect

- [Create a Patterns Account](https://www.patterns.app/beta)
