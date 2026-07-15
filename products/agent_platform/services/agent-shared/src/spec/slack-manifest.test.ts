import { buildSlackManifest, BuildSlackManifestInput } from './slack-manifest'
import type { ToolRef, Trigger } from './spec'

const SLACK_TOOL_SCOPES: Record<string, string[]> = {
    '@posthog/slack-post-message': ['chat:write'],
    '@posthog/slack-read-thread': ['channels:history', 'groups:history'],
    '@posthog/slack-react': ['reactions:write'],
}
const scopesForNativeTool = (id: string): string[] => SLACK_TOOL_SCOPES[id] ?? []

function slackTrigger(config: Partial<Extract<Trigger, { type: 'slack' }>['config']> = {}): Trigger {
    return {
        type: 'slack',
        config: { trusted_workspaces: ['T01'], mention_only: false, auto_resume_threads: false, ...config },
    } as Trigger
}

function nativeTool(id: string, requires_approval = false): ToolRef {
    return { kind: 'native', id, requires_approval, approval_policy: {} } as unknown as ToolRef
}

function build(overrides: Partial<BuildSlackManifestInput> = {}): ReturnType<typeof buildSlackManifest> {
    return buildSlackManifest({
        triggers: [slackTrigger()],
        tools: [],
        displayName: 'On-call bot',
        displayDescription: 'Reports who is on call',
        eventsUrl: 'https://ingress.example/agents/oncall-bot/slack/events',
        interactivityUrl: 'https://ingress.example/agents/oncall-bot/slack/interactivity',
        scopesForNativeTool,
        ...overrides,
    })
}

describe('buildSlackManifest', () => {
    it('throws when the spec has no slack trigger', () => {
        expect(() =>
            build({
                triggers: [
                    {
                        type: 'chat',
                        config: {},
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    } as Trigger,
                ],
            })
        ).toThrow('no_slack_trigger')
    })

    it('mention_only=true + auto_resume_threads=false → no channel message events or history scopes', () => {
        const { manifest } = build({ triggers: [slackTrigger({ mention_only: true, auto_resume_threads: false })] })
        // No channel message events / history scopes when only mentions are watched…
        expect(manifest.settings.event_subscriptions.bot_events).not.toContain('message.channels')
        expect(manifest.settings.event_subscriptions.bot_events).not.toContain('message.groups')
        expect(manifest.oauth_config.scopes.bot).not.toContain('channels:history')
        expect(manifest.oauth_config.scopes.bot).not.toContain('groups:history')
        // …but app_mention + the always-on agent surface (DMs) are still there.
        expect(manifest.settings.event_subscriptions.bot_events).toContain('app_mention')
        expect(manifest.settings.event_subscriptions.bot_events).toContain('message.im')
    })

    it('auto_resume_threads=true → subscribes to message.* and adds history scopes', () => {
        const { manifest } = build({ triggers: [slackTrigger({ mention_only: true, auto_resume_threads: true })] })
        expect(manifest.settings.event_subscriptions.bot_events).toContain('message.channels')
        expect(manifest.settings.event_subscriptions.bot_events).toContain('message.groups')
        expect(manifest.oauth_config.scopes.bot).toContain('channels:history')
        expect(manifest.oauth_config.scopes.bot).toContain('groups:history')
    })

    it('mention_only=false (watch the channel) → message.* events even without auto_resume', () => {
        const { manifest } = build({ triggers: [slackTrigger({ mention_only: false, auto_resume_threads: false })] })
        expect(manifest.settings.event_subscriptions.bot_events).toContain('message.channels')
    })

    it('every agent is a native DM-able agent surface → DM events, im/mpim history scopes, Messages tab', () => {
        const { manifest } = build({ triggers: [slackTrigger({ mention_only: true })] })
        expect(manifest.settings.event_subscriptions.bot_events).toContain('message.im')
        expect(manifest.settings.event_subscriptions.bot_events).toContain('message.mpim')
        expect(manifest.oauth_config.scopes.bot).toContain('im:history')
        expect(manifest.oauth_config.scopes.bot).toContain('mpim:history')
        expect(manifest.features.app_home).toEqual({
            messages_tab_enabled: true,
            messages_tab_read_only_enabled: false,
        })
    })

    it('ack_reaction adds reactions:write', () => {
        const { manifest } = build({ triggers: [slackTrigger({ mention_only: true, ack_reaction: 'eyes' })] })
        expect(manifest.oauth_config.scopes.bot).toContain('reactions:write')
    })

    it("unions the agent's @posthog/slack-* tool scopes (and ignores non-slack tools)", () => {
        const { manifest } = build({
            triggers: [slackTrigger({ mention_only: true })],
            tools: [nativeTool('@posthog/slack-read-thread'), nativeTool('@posthog/query')],
        })
        expect(manifest.oauth_config.scopes.bot).toContain('channels:history')
        expect(manifest.oauth_config.scopes.bot).toContain('groups:history')
        // @posthog/query is not a slack tool — its scopes must not leak in.
        expect(manifest.oauth_config.scopes.bot).not.toContain('query:read')
    })

    it('enables interactivity only when a tool requires approval', () => {
        expect(build().manifest.settings.interactivity).toBeUndefined()
        const gated = build({ tools: [nativeTool('@posthog/slack-post-message', true)] })
        expect(gated.manifest.settings.interactivity).toEqual({
            is_enabled: true,
            request_url: 'https://ingress.example/agents/oncall-bot/slack/interactivity',
        })
    })

    it('uses placeholders + a note when no public ingress URL is configured', () => {
        const { manifest, notes } = build({ eventsUrl: null, interactivityUrl: null })
        expect(manifest.settings.event_subscriptions.request_url).toContain('AGENT_INGRESS_PUBLIC_URL')
        expect(notes.some((n) => n.includes('AGENT_INGRESS_PUBLIC_URL'))).toBe(true)
    })

    it('always reminds the user to invite the bot to its channels', () => {
        expect(build().notes.some((n) => n.toLowerCase().includes('invite the bot'))).toBe(true)
    })

    it('truncates display name (35) and description (140) to Slack limits', () => {
        const { manifest } = build({ displayName: 'x'.repeat(50), displayDescription: 'y'.repeat(200) })
        expect(manifest.display_information.name).toHaveLength(35)
        expect(manifest.display_information.description).toHaveLength(140)
        expect(manifest.features.bot_user.display_name).toHaveLength(35)
    })

    it('trims an over-long description at a word boundary, ending with an ellipsis', () => {
        const longDesc = `${'kudos '.repeat(40)}end`
        const { manifest } = build({ displayDescription: longDesc })
        const desc = manifest.display_information.description ?? ''
        expect(desc.length).toBeLessThanOrEqual(140)
        expect(desc.endsWith('…')).toBe(true)
        const kept = desc.slice(0, -1)
        expect(longDesc.startsWith(kept)).toBe(true) // a clean prefix, not mangled
        expect(longDesc[kept.length]).toBe(' ') // cut fell on a word boundary
    })

    it('every agent gets the native agent surface → agent_view, assistant:write, App Home, assistant events', () => {
        const { manifest, notes } = build({
            triggers: [
                slackTrigger({
                    mention_only: true,
                    agent_description: 'Ask me about on-call',
                    suggested_prompts: [{ title: "Who's on call?", message: 'Who is on call right now?' }],
                }),
            ],
        })
        expect(manifest.oauth_config.scopes.bot).toContain('assistant:write')
        expect(manifest.features.agent_view).toEqual({
            agent_description: 'Ask me about on-call',
            suggested_prompts: [{ title: "Who's on call?", message: 'Who is on call right now?' }],
        })
        expect(manifest.features.app_home).toEqual({
            messages_tab_enabled: true,
            messages_tab_read_only_enabled: false,
        })
        expect(manifest.settings.event_subscriptions.bot_events).toContain('assistant_thread_started')
        expect(manifest.settings.event_subscriptions.bot_events).toContain('app_home_opened')
        expect(manifest.settings.event_subscriptions.bot_events).toContain('message.im')
        expect(manifest.oauth_config.scopes.bot).toContain('im:history')
        expect(notes.some((n) => n.toLowerCase().includes('native slack agent surface'))).toBe(true)
    })

    it('agent_view is emitted even with no description/prompts (its presence selects the surface)', () => {
        const { manifest } = build({ triggers: [slackTrigger({ mention_only: true })] })
        expect(manifest.features.agent_view).toEqual({})
    })
})
