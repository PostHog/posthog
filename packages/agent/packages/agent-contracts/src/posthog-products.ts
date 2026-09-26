export const POSTHOG_PRODUCTS = {
  product_analytics: "Product analytics",
  web_analytics: "Web analytics",
  feature_flags: "Feature flags",
  experiments: "Experiments",
  error_tracking: "Error tracking",
  session_replay: "Session replay",
  surveys: "Surveys",
  llm_analytics: "AI observability",
  data_warehouse: "Data warehouse",
  cdp: "Data pipelines",
  logs: "Logs",
  apm: "APM",
  sql: "SQL",
} as const;

export type PostHogProductId = keyof typeof POSTHOG_PRODUCTS;
