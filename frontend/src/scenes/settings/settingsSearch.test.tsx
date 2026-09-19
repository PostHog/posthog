import { matchesFlagDefinition } from './flagGating'
import { SETTINGS_MAP } from './SettingsMap'
import { buildSettingsSearchIndex, createSettingsSearchFuse, searchSettingsIndex } from './settingsSearch'
import { Setting, SettingSection } from './types'

const SECTIONS: SettingSection[] = [
    {
        level: 'environment',
        id: 'environment-details',
        title: 'General',
        settings: [
            {
                id: 'variables',
                title: 'Project token & ID',
                description: 'Your project token and ID used to connect SDKs and APIs to this environment.',
                component: <div />,
                keywords: ['api key', 'token', 'project id'],
            },
            {
                id: 'js-snippet-version',
                title: (
                    <>
                        Snippet version <span>Experimental</span>
                    </>
                ),
                description: 'Pin the snippet to a specific version of posthog-js.',
                component: <div />,
                keywords: ['pin', 'posthog-js'],
            },
        ],
    },
    {
        level: 'environment',
        id: 'environment-replay',
        title: 'Session replay',
        settings: [
            {
                id: 'replay-retention',
                title: 'Data retention',
                description: 'Control how long your recordings are stored.',
                component: <div />,
                keywords: ['storage', 'retention', 'delete', 'days', 'months'],
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-details',
        title: 'General',
        settings: [
            {
                id: 'organization-ai-consent',
                title: 'AI service providers',
                component: <div />,
                keywords: ['ai', 'max', 'llm', 'consent', 'approve', 'enable', 'opt-in', 'data sharing'],
                searchDescription: 'PostHog AI features use external AI services for data analysis.',
            },
            {
                id: 'organization-ai-training-opt-out',
                title: 'Internal AI training',
                component: <div />,
                keywords: ['ai', 'training', 'opt-out', 'opt-in', 'model', 'max'],
            },
        ],
    },
    {
        level: 'organization',
        id: 'organization-billing',
        title: 'Billing',
        to: '/organization/billing',
        settings: [],
        keywords: ['usage', 'subscription', 'invoice', 'plan', 'payment', 'spend', 'quota', 'credits', 'card'],
    },
]

const search = (term: string, isSettingVisible: (setting: Setting) => boolean = () => true): string[] => {
    const fuse = createSettingsSearchFuse(buildSettingsSearchIndex(SECTIONS, isSettingVisible))
    return searchSettingsIndex(fuse, term).map((entry) => entry.settingId)
}

describe('settingsSearch', () => {
    test.each([
        ['a single word', 'retention', 'replay-retention'],
        ['a trailing space', 'project id ', 'variables'],
        ['a leading space', ' project id', 'variables'],
        ['a repeated space', 'project  id', 'variables'],
        ['trailing punctuation', 'project id?', 'variables'],
        ['words split across the title and the section title', 'session replay retention', 'replay-retention'],
        ['a keyword late in the keyword list', 'max', 'organization-ai-training-opt-out'],
        ['an action phrased query', 'enable AI', 'organization-ai-consent'],
        ['a synonym on a section that has no settings', 'usage', 'organization-billing'],
        ['a word the index does not carry alongside one it does', 'usage dashboard', 'organization-billing'],
    ])('finds a setting by %s', (_description, term, expectedSettingId) => {
        expect(search(term)).toContain(expectedSettingId)
    })

    it('indexes a JSX title by the words it shows, not by its id', () => {
        const entries = buildSettingsSearchIndex(SECTIONS, () => true)
        const snippetVersion = entries.find((entry) => entry.settingId === 'js-snippet-version')

        expect(snippetVersion?.settingTitle).toBe('Snippet version Experimental')
        expect(search('snippet version')).toContain('js-snippet-version')
    })

    it('leaves out a setting that is not visible to this user', () => {
        const isVisible = (setting: Setting): boolean => setting.id !== 'organization-ai-training-opt-out'

        expect(search('internal AI training', isVisible)).not.toContain('organization-ai-training-opt-out')
    })

    it('returns nothing for a term that is only whitespace', () => {
        expect(search('   ')).toEqual([])
    })

    // Integration guides ask for the public project token under several names, and without
    // those synonyms a search for one of them puts personal API keys on top instead. Searches
    // the shipped map, not a fixture, because the synonyms have to stay on the setting itself.
    test.each(['client api key', 'public api key', 'write key'])('puts the project token first for "%s"', (term) => {
        const visible = (definition: Pick<Setting, 'flag'>): boolean => matchesFlagDefinition(definition.flag, {})
        const fuse = createSettingsSearchFuse(buildSettingsSearchIndex(SETTINGS_MAP.filter(visible), visible))

        expect(searchSettingsIndex(fuse, term)[0]?.settingId).toBe('variables')
    })
})
