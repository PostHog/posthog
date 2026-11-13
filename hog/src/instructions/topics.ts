import api from './api.md' with { type: 'text' }
import auth from './auth.md' with { type: 'text' }
import endpoints from './endpoints.md' with { type: 'text' }
import root from './root.md' with { type: 'text' }

export interface Topic {
    name: string
    description: string
    text: string
}

// A topic covers a workflow that spans several commands, which no single `--help` can show.
export const TOPICS: readonly Topic[] = [
    { name: 'auth', description: 'Log in, pick the project, add scopes, and set up CI', text: auth },
    { name: 'api', description: 'Find, check and call PostHog API tools', text: api },
    { name: 'endpoints', description: 'Keep endpoints as YAML files: pull, run, diff and push', text: endpoints },
]

export function rootText(): string {
    const topics = TOPICS.map((topic) => `- \`hog instructions ${topic.name}\`: ${topic.description}`)
    return [root.trimEnd(), '', '## Topics', '', ...topics, ''].join('\n')
}
