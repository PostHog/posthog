import { readFileSync } from "node:fs";
import {
  type GatewayModel,
  normalizeGatewayModelsResponse,
} from "../cloud-task-models";

const BACKEND_TESTS = new URL(
  "../../../../../../products/tasks/backend/tests/",
  import.meta.url,
);

function read(path: string): unknown {
  return JSON.parse(readFileSync(new URL(path, BACKEND_TESTS), "utf8"));
}

export function savedGatewayListing(): unknown {
  return read("fixtures/gateway_models.json");
}

export function rememberSavedGatewayListing(): GatewayModel[] {
  return normalizeGatewayModelsResponse(savedGatewayListing());
}

export function backendOfferedModels(product: string): string[] {
  const snapshot = read(
    "__snapshots__/test_gateway_model_pin/test_what_each_product_may_call_and_offer_from_the_saved_listing.json",
  ) as Record<string, { offered: string[] }>;
  return snapshot[product].offered;
}
