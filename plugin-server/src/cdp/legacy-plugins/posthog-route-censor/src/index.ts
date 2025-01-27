import { Plugin, PluginEvent, PluginInput, PluginMeta } from '@posthog/plugin-scaffold';
import { censorProperties } from 'utils/censorProperties';

export const setupPlugin = ({ global, config, attachments }: any) => {
  global.properties = config.properties.split(',');
  global.setProperties = config.set_properties.split(',');
  global.setOnceProperties = config.set_once_properties.split(',');
  global.routes = attachments?.routes?.contents ? JSON.parse(attachments?.routes?.contents) : undefined;

  console.debug('Plugin set up with global config: ', JSON.stringify(global, null, 2));
};

/**
 * Runs on every event
 *
 * @param event PostHog event
 * @param meta metadata defined in the plugin.json
 * @returns modified event
 */
export const processEvent = (event: PluginEvent, { global }: PluginMeta<Plugin<PluginInput>>): PluginEvent => {
  // If we don't have routes to censor, then just return the input event.
  if (!global.routes?.length) {
    return event;
  }

  return {
    ...event,
    properties: {
      ...event.properties,
      ...censorProperties(event.properties, global.routes, global.properties),
    },
    $set: {
      ...event.$set,
      ...censorProperties(event.$set, global.routes, global.setProperties),
    },
    $set_once: {
      ...event.$set_once,
      ...censorProperties(event.$set_once, global.routes, global.setOnceProperties),
    },
  };
};
