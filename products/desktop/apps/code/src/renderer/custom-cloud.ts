import { configureCustomCloud, readCustomCloudFromEnv } from "@posthog/shared";

// The renderer has no `process.env`, so the target comes from the values Vite
// compiled in. Runs as a side effect before any module reads a region URL.
configureCustomCloud(
  readCustomCloudFromEnv(
    import.meta.env as unknown as Record<string, string | undefined>,
  ),
);
