import { Scene } from 'scenes/sceneTypes'

import { SidePanelTab } from '~/types'

import { type PhaiOnboardingHost, type PhaiOnboardingHostInput, resolvePhaiOnboardingHost } from './phaiOnboardingHost'

describe('resolvePhaiOnboardingHost', () => {
    const base: PhaiOnboardingHostInput = {
        sceneId: Scene.Dashboards,
        receivedFeatureFlags: true,
        effectivePhaiView: 'legacy',
        sidePanelOpen: false,
        selectedTab: null,
    }

    const cases: [string, Partial<PhaiOnboardingHostInput>, PhaiOnboardingHost][] = [
        ['the AI scene on the new view', { sceneId: Scene.Max, effectivePhaiView: 'new' }, 'scene'],
        ['the AI scene on the legacy view', { sceneId: Scene.Max }, null],
        [
            'the AI scene before the flags land',
            { sceneId: Scene.Max, effectivePhaiView: 'new', receivedFeatureFlags: false },
            null,
        ],
        [
            'the side panel on the new view',
            { effectivePhaiView: 'new', sidePanelOpen: true, selectedTab: SidePanelTab.Max },
            'side-panel',
        ],
        ['the side panel on the legacy view', { sidePanelOpen: true, selectedTab: SidePanelTab.Max }, null],
        [
            'the AI scene with the side panel open too',
            { sceneId: Scene.Max, effectivePhaiView: 'new', sidePanelOpen: true, selectedTab: SidePanelTab.Max },
            'scene',
        ],
        ['the tasks scene without the PostHog AI view', { sceneId: Scene.TaskTracker }, 'scene'],
        ['the tasks scene before the flags land', { sceneId: Scene.TaskTracker, receivedFeatureFlags: false }, 'scene'],
        ['another scene on the new view', { effectivePhaiView: 'new' }, null],
        [
            'another side panel tab on the new view',
            { effectivePhaiView: 'new', sidePanelOpen: true, selectedTab: SidePanelTab.Support },
            null,
        ],
    ]

    it.each(cases)('resolves %s to %j', (_name, overrides, expected) => {
        expect(resolvePhaiOnboardingHost({ ...base, ...overrides })).toEqual(expected)
    })
})
