import { readFileSync } from "node:fs";
import {
  type GatewayModel,
  normalizeGatewayModelsResponse,
} from "../cloud-task-models";

function read(name: string): unknown {
  const file = new URL(`../../testing/${name}`, import.meta.url);
  return JSON.parse(readFileSync(file, "utf8"));
}

export function savedGatewayListing(): unknown {
  return read("gateway-models.json");
}

export function rememberSavedGatewayListing(): GatewayModel[] {
  return normalizeGatewayModelsResponse(savedGatewayListing());
}

export function backendOfferedModels(): string[] {
  return read("offered-models.json") as string[];
}
