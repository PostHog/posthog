import { Scene } from 'scenes/sceneTypes'

import { SidePanelTab } from '~/types'

import {
    type PhaiOnboardingHostInput,
    type PhaiOnboardingMount,
    resolvePhaiOnboardingMounts,
} from './phaiOnboardingHost'

describe('resolvePhaiOnboardingMounts', () => {
    const base: PhaiOnboardingHostInput = {
        sceneId: Scene.Dashboards,
        receivedFeatureFlags: true,
        effectivePhaiView: 'legacy',
        sidePanelOpen: false,
        selectedTab: null,
    }

    const cases: [string, Partial<PhaiOnboardingHostInput>, PhaiOnboardingMount[]][] = [
        [
            'the AI scene on the new view',
            { sceneId: Scene.Max, effectivePhaiView: 'new' },
            [{ host: 'scene', autoOpen: true }],
        ],
        ['the AI scene on the legacy view', { sceneId: Scene.Max }, []],
        [
            'the AI scene before the flags land',
            { sceneId: Scene.Max, effectivePhaiView: 'new', receivedFeatureFlags: false },
            [],
        ],
        [
            'the side panel on the new view',
            { effectivePhaiView: 'new', sidePanelOpen: true, selectedTab: SidePanelTab.Max },
            [{ host: 'side-panel', autoOpen: true }],
        ],
        ['the side panel on the legacy view', { sidePanelOpen: true, selectedTab: SidePanelTab.Max }, []],
        [
            'the AI scene with the side panel open too',
            { sceneId: Scene.Max, effectivePhaiView: 'new', sidePanelOpen: true, selectedTab: SidePanelTab.Max },
            [{ host: 'scene', autoOpen: true }],
        ],
        [
            'the tasks scene without the PostHog AI view',
            { sceneId: Scene.TaskTracker },
            [{ host: 'scene', autoOpen: false }],
        ],
        [
            'the tasks scene on the new view',
            { sceneId: Scene.TaskTracker, effectivePhaiView: 'new' },
            [{ host: 'scene', autoOpen: false }],
        ],
        [
            'the tasks scene with the side panel open',
            {
                sceneId: Scene.TaskTracker,
                effectivePhaiView: 'new',
                sidePanelOpen: true,
                selectedTab: SidePanelTab.Max,
            },
            [
                { host: 'side-panel', autoOpen: true },
                { host: 'scene', autoOpen: false },
            ],
        ],
        ['another scene on the new view', { effectivePhaiView: 'new' }, []],
        [
            'another side panel tab on the new view',
            { effectivePhaiView: 'new', sidePanelOpen: true, selectedTab: SidePanelTab.Support },
            [],
        ],
    ]

    it.each(cases)('resolves %s to %j', (_name, overrides, expected) => {
        expect(resolvePhaiOnboardingMounts({ ...base, ...overrides })).toEqual(expected)
    })
})
