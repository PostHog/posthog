export interface Shortcut {
    use: string
    description: string
}

// Top-level names for a command inside a group, as `hog whoami` for `hog auth status`. hog runs the
// command a shortcut names, so its help, errors and usage events name that command. A Map, because
// the name comes from the command line, and an object lookup would also match `constructor`.
export const SHORTCUTS: ReadonlyMap<string, Shortcut> = new Map([
    ['whoami', { use: 'auth status', description: 'Show who hog is logged in as' }],
    [
        'check',
        { use: 'stack check', description: 'Check the stack in this folder without sending anything to PostHog' },
    ],
    ['diff', { use: 'stack diff', description: 'Show the changes a stack would make in PostHog' }],
    ['push', { use: 'stack push', description: 'Push a reviewed diff to PostHog' }],
    ['pull', { use: 'stack pull', description: 'Bring changes or existing entities into a stack' }],
    ['init', { use: 'stack init', description: 'Create a folder for PostHog definitions' }],
])
