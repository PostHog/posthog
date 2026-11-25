import { readFileSync } from "node:fs";
import { normalizeGatewayModelsResponse } from "@posthog/agent-contracts";
import { beforeEach } from "vitest";

const SAVED_GATEWAY_LISTING: unknown = JSON.parse(
  readFileSync(
    new URL(
      "../../../agent-contracts/testing/gateway-models.json",
      import.meta.url,
    ),
    "utf8",
  ),
);

beforeEach(() => {
  normalizeGatewayModelsResponse(SAVED_GATEWAY_LISTING);
});
