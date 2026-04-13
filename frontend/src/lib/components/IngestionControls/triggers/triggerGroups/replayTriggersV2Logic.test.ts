import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { replayTriggersV2Logic } from './replayTriggersV2Logic'

describe('replayTriggersV2Logic', () => {
    let logic: ReturnType<typeof replayTriggersV2Logic.build>

    beforeEach(() => {
        initKeaTests()
        logic = replayTriggersV2Logic()
        logic.mount()
    })

    describe('previewLegacyGroups selector', () => {
        it.each([
            [
                'single group when match type is ALL',
                {
                    session_recording_sample_rate: '0.5',
                    session_recording_minimum_duration_milliseconds: 5000,
                    session_recording_trigger_match_type_config: 'all',
                    session_recording_url_trigger_config: [{ url: '^/checkout$', matching: 'regex' }],
                    session_recording_event_trigger_config: ['$pageview'],
                },
                [
                    {
                        id: expect.any(String),
                        name: 'Migrated trigger conditions',
                        sampleRate: 0.5,
                        minDurationMs: 5000,
                        conditions: {
                            matchType: 'all',
                            urls: [{ url: '^/checkout$', matching: 'regex' }],
                            events: [{ name: '$pageview' }],
                            flag: undefined,
                        },
                    },
                ],
            ],
            [
                'single group when there are no triggers',
                {
                    session_recording_sample_rate: '0.3',
                    session_recording_minimum_duration_milliseconds: 10000,
                    session_recording_trigger_match_type_config: 'any',
                },
                [
                    {
                        id: expect.any(String),
                        name: 'Migrated trigger conditions',
                        sampleRate: 0.3,
                        minDurationMs: 10000,
                        conditions: {
                            matchType: 'any',
                            urls: undefined,
                            events: undefined,
                            flag: undefined,
                        },
                    },
                ],
            ],
            [
                'single group when match type is ANY but sampling is 100%',
                {
                    session_recording_sample_rate: '1',
                    session_recording_trigger_match_type_config: 'any',
                    session_recording_url_trigger_config: [{ url: '^/checkout$', matching: 'regex' }],
                },
                [
                    {
                        id: expect.any(String),
                        name: 'Migrated trigger conditions',
                        sampleRate: 1,
                        minDurationMs: undefined,
                        conditions: {
                            matchType: 'any',
                            urls: [{ url: '^/checkout$', matching: 'regex' }],
                            events: undefined,
                            flag: undefined,
                        },
                    },
                ],
            ],
            [
                '2 groups when match type is ANY with triggers and sampling < 100%',
                {
                    session_recording_sample_rate: '0.1',
                    session_recording_minimum_duration_milliseconds: 2000,
                    session_recording_trigger_match_type_config: 'any',
                    session_recording_url_trigger_config: [
                        { url: '^/checkout$', matching: 'regex' },
                        { url: '^/payment$', matching: 'regex' },
                    ],
                    session_recording_event_trigger_config: ['invited_team_member', 'signed_up'],
                },
                [
                    {
                        id: expect.any(String),
                        name: 'Migrated trigger conditions',
                        sampleRate: 1,
                        minDurationMs: 2000,
                        conditions: {
                            matchType: 'any',
                            urls: [
                                { url: '^/checkout$', matching: 'regex' },
                                { url: '^/payment$', matching: 'regex' },
                            ],
                            events: [{ name: 'invited_team_member' }, { name: 'signed_up' }],
                            flag: undefined,
                        },
                    },
                    {
                        id: expect.any(String),
                        name: 'Migrated baseline sampling',
                        sampleRate: 0.1,
                        minDurationMs: 2000,
                        conditions: {
                            matchType: 'all',
                        },
                    },
                ],
            ],
        ])('creates %s', async (_description, teamConfig, expected) => {
            await expectLogic(logic, () => {
                teamLogic.actions.loadCurrentTeamSuccess({
                    id: 1,
                    ...teamConfig,
                } as any)
            }).toMatchValues({
                previewLegacyGroups: expected,
            })
        })
    })
})
