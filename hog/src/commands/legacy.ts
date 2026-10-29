import { defineLegacy, type CommandTree } from '@/core/command'

export const LEGACY_COMMANDS: CommandTree = {
    endpoints: defineLegacy({ description: 'Manage PostHog endpoints', use: 'posthog-cli exp endpoints' }),
    logs: defineLegacy({
        description: 'Import historical logs from another log store into PostHog',
        use: 'posthog-cli exp logs',
    }),
    tasks: defineLegacy({ description: 'List, track and update PostHog tasks', use: 'posthog-cli exp task' }),
    update: defineLegacy({ description: 'Update hog to the latest version', use: 'posthog-cli update' }),
}
