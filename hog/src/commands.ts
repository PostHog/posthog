export interface CommandSpec {
    name: string
    summary: string
    // The posthog-cli invocation that covers this command until hog implements it.
    legacyCommand: string
}

export const COMMANDS: readonly CommandSpec[] = [
    {
        name: 'login',
        summary: 'Log in to PostHog and store a personal API key on this machine',
        legacyCommand: 'posthog-cli login',
    },
    { name: 'api', summary: 'Agent-first PostHog API tools', legacyCommand: 'posthog-cli api' },
    { name: 'query', summary: 'Run and check SQL queries', legacyCommand: 'posthog-cli exp query' },
    { name: 'endpoints', summary: 'Manage PostHog endpoints', legacyCommand: 'posthog-cli exp endpoints' },
    {
        name: 'logs',
        summary: 'Import historical logs from another log store into PostHog',
        legacyCommand: 'posthog-cli exp logs',
    },
    { name: 'tasks', summary: 'List, track and update PostHog tasks', legacyCommand: 'posthog-cli exp task' },
    {
        name: 'schema',
        summary: 'Download event definitions and generate a typed SDK',
        legacyCommand: 'posthog-cli exp schema',
    },
    {
        name: 'sourcemap',
        summary: 'Inject chunk IDs into bundles and upload their sourcemaps',
        legacyCommand: 'posthog-cli sourcemap',
    },
    { name: 'hermes', summary: 'Upload Hermes sourcemaps to PostHog', legacyCommand: 'posthog-cli hermes' },
    { name: 'dsym', summary: 'Upload Apple dSYM debug symbol files to PostHog', legacyCommand: 'posthog-cli dsym' },
    { name: 'proguard', summary: 'Upload ProGuard mapping files to PostHog', legacyCommand: 'posthog-cli proguard' },
    {
        name: 'symbol-sets',
        summary: 'Upload, download, and manage symbol sets',
        legacyCommand: 'posthog-cli symbol-sets',
    },
    { name: 'release', summary: 'Look up the release a build belongs to', legacyCommand: 'posthog-cli release' },
    { name: 'update', summary: 'Update hog to the latest version', legacyCommand: 'posthog-cli update' },
]
