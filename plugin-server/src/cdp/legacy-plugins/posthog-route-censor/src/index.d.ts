import { Plugin, PluginEvent, PluginInput, PluginMeta } from '@posthog/plugin-scaffold';
export declare const setupPlugin: ({ global, config }: any) => void;
/**
 * Runs on every event
 *
 * @param event PostHog event
 * @param meta metadata defined in the plugin.json
 * @returns modified event
 */
export declare const processEvent: (event: PluginEvent, { global }: PluginMeta<Plugin<PluginInput>>) => PluginEvent;
