import { ProcessedPluginEvent } from '@posthog/plugin-scaffold'

import { LegacyPlugin, LegacyPluginMeta } from '../types'
import metadata from './plugin.json'

import {
  PluginInput,
  RetryError,
} from "@posthog/plugin-scaffold";
import { Response } from "~/src/utils/fetch";

type PatternsMeta = LegacyPluginMeta & {
  config: {
    webhookUrl: string;
    allowedEventTypes: string;
  }
  global: {
    allowedEventTypesSet: Set<string>;
  }
}

// Plugin method that runs on plugin load
//@ts-ignore
export async function setupPlugin({ config, global }: PatternsMeta): Promise<void> {
  if (config.allowedEventTypes) {
    let allowedEventTypes = config.allowedEventTypes.split(",");
    allowedEventTypes = allowedEventTypes.map((eventType: string) => eventType.trim());
    global.allowedEventTypesSet = new Set(allowedEventTypes);
  }
}

// Plugin method to export events
const onEvent = async (
  event: ProcessedPluginEvent,
  { config, global, fetch }: PatternsMeta
): Promise<void> => {
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

export const patternsPlugin: LegacyPlugin = {
  id: 'patterns',
  metadata: metadata as any,
  setupPlugin: setupPlugin as any,
  onEvent,
}
