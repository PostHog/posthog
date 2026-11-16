import { defineLegacy, type CommandTree } from '@/core/command'

export const LEGACY_COMMANDS: CommandTree = {
    logs: defineLegacy({
        description: 'Import historical logs from another log store into PostHog',
        use: 'posthog-cli exp logs',
    }),
    tasks: defineLegacy({ description: 'List, track and update PostHog tasks', use: 'posthog-cli exp task' }),
    upgrade: defineLegacy({ description: 'Upgrade hog to the latest version', use: 'posthog-cli update' }),
}
