import {
  PluginInput,
  Plugin,
  Meta,
  RetryError,
} from "@posthog/plugin-scaffold";
import fetch, { Response } from "node-fetch";

type PatternsInputs = {
  webhookUrl: string;
  allowedEventTypes: string;
};

export interface PatternsPluginInput extends PluginInput {
  config: PatternsInputs;
}

// Plugin method that runs on plugin load
//@ts-ignore
export async function setupPlugin({ config, global }: Meta<PatternsPluginInput>) {
  if (config.allowedEventTypes) {
    let allowedEventTypes = config.allowedEventTypes.split(",");
    allowedEventTypes = allowedEventTypes.map((eventType: string) => eventType.trim());
    global.allowedEventTypesSet = new Set(allowedEventTypes);
  }
}

// Plugin method to export events
export const onEvent: Plugin<PatternsPluginInput>["onEvent"] = async (
  event,
  { config, global }: Meta<PatternsPluginInput>
) => {
  if (global.allowedEventTypesSet) {
    if (!global.allowedEventTypesSet.has(event.event)) {
      return
    }
  }
  
  let response: Response;
  response = await fetch(config.webhookUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify([event]),
  });

  if (response.status != 200) {
    const data = await response.json();
    throw new RetryError(`Export events failed: ${JSON.stringify(data)}`);
  }
};
