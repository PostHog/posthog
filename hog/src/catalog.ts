export interface CommandSpec {
    name: string
    summary: string
    // The posthog-cli invocation that covers this command until hog implements it.
    legacyCommand: string
    // Whether hog implements the command itself.
    available: boolean
}

export const COMMANDS: readonly CommandSpec[] = [
    {
        name: 'login',
        summary: 'Log in to PostHog and store a personal API key on this machine',
        legacyCommand: 'posthog-cli login',
        available: false,
    },
    { name: 'api', summary: 'Agent-first PostHog API tools', legacyCommand: 'posthog-cli api', available: false },
    {
        name: 'query',
        summary: 'Run and check HogQL queries against your project',
        legacyCommand: 'posthog-cli exp query',
        available: true,
    },
    {
        name: 'endpoints',
        summary: 'Manage PostHog endpoints',
        legacyCommand: 'posthog-cli exp endpoints',
        available: false,
    },
    {
        name: 'logs',
        summary: 'Import historical logs from another log store into PostHog',
        legacyCommand: 'posthog-cli exp logs',
        available: false,
    },
    {
        name: 'tasks',
        summary: 'List, track and update PostHog tasks',
        legacyCommand: 'posthog-cli exp task',
        available: false,
    },
    {
        name: 'schema',
        summary: 'Download event definitions and generate a typed SDK',
        legacyCommand: 'posthog-cli exp schema',
        available: false,
    },
    {
        name: 'sourcemap',
        summary: 'Inject chunk IDs into bundles and upload their sourcemaps',
        legacyCommand: 'posthog-cli sourcemap',
        available: false,
    },
    {
        name: 'hermes',
        summary: 'Upload Hermes sourcemaps to PostHog',
        legacyCommand: 'posthog-cli hermes',
        available: false,
    },
    {
        name: 'dsym',
        summary: 'Upload Apple dSYM debug symbol files to PostHog',
        legacyCommand: 'posthog-cli dsym',
        available: false,
    },
    {
        name: 'proguard',
        summary: 'Upload ProGuard mapping files to PostHog',
        legacyCommand: 'posthog-cli proguard',
        available: false,
    },
    {
        name: 'symbol-sets',
        summary: 'Upload, download, and manage symbol sets',
        legacyCommand: 'posthog-cli symbol-sets',
        available: false,
    },
    {
        name: 'release',
        summary: 'Look up the release a build belongs to',
        legacyCommand: 'posthog-cli release',
        available: false,
    },
    {
        name: 'update',
        summary: 'Update hog to the latest version',
        legacyCommand: 'posthog-cli update',
        available: false,
    },
]
