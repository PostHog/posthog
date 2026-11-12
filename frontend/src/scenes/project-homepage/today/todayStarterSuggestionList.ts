import type { NewSessionSuggestion } from 'products/tasks/frontend/spaces/newSessionSuggestionDefaults'

export const TODAY_STARTER_SUGGESTIONS: NewSessionSuggestion[] = [
    {
        id: 'starter-install',
        label: 'Install PostHog in my app',
        description: 'Add the SDK and capture the first events',
        icon: 'code',
        mode: 'auto',
        prompt: 'Install PostHog in my app. Add the SDK, identify users after they sign in, and capture the events that show how people use the product. Open a pull request with the changes.\n\n\nUser input:\n- Repository:\n- Framework (optional):',
    },
    {
        id: 'starter-tracking-plan',
        label: 'Plan what to track',
        description: 'Events for sign-ups, activation and payments',
        icon: 'trends',
        mode: 'auto',
        prompt: 'Read my code and suggest the events to capture for sign-ups, activation and payments. For each event, give its name, its properties and where in the code to capture it.\n\n\nUser input:\n- Repository:\n- What counts as an active user (optional):',
    },
    {
        id: 'starter-error-tracking',
        label: 'Set up error tracking',
        description: 'Capture exceptions with readable stack traces',
        icon: 'bug',
        mode: 'auto',
        prompt: 'Set up PostHog error tracking in my app. Capture unhandled exceptions, upload source maps so stack traces are readable, and open a pull request with the changes.\n\n\nUser input:\n- Repository:',
    },
    {
        id: 'starter-dashboard',
        label: 'Build my first dashboard',
        description: 'Charts for the numbers that matter',
        icon: 'canvas',
        mode: 'auto',
        prompt: 'Build a dashboard with the numbers that matter for my product, such as active users, sign-ups and retention. Use the events my project already captures.\n\n\nUser input:\n- What the product does:',
    },
]
