import { act, cleanup, render, screen } from '@testing-library/react'
import { kea, path } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { ProductEmptyStateGate } from './ProductEmptyStateGate'
import { productSetupStatusLogic } from './productSetupStatusLogic'
import type { ProductEmptyStateConfig, ProductSetupStatus, SceneProductEmptyState } from './types'

const config: ProductEmptyStateConfig = {
    productKey: ProductKey.EXPERIMENTS,
    productName: 'Experiments',
    icon: <span />,
    accentColor: 'red',
    text: { 'needs-setup': { headline: 'Set up experiments', lead: 'Lead' } },
    previewLabel: 'Preview',
    Preview: () => <div />,
}

const noopStatusLogic = kea([path(['lib', 'components', 'ProductEmptyState', 'testNoopStatusLogic'])])

const emptyState: SceneProductEmptyState = { config, statusLogic: noopStatusLogic }

const tabScopedEmptyState: SceneProductEmptyState = {
    config: {
        ...config,
        productKey: ProductKey.WORKFLOWS,
        productName: 'Workflows',
        text: { 'needs-setup': { headline: 'Set up workflows', lead: 'Lead' } },
    },
    statusLogic: noopStatusLogic,
    scenes: [{ scene: Scene.Workflows, tabs: [undefined, 'workflows'] }],
}

describe('ProductEmptyStateGate', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/_preflight/': { cloud: false },
                '/api/environments/@current/': {},
                '/api/users/@me/': {},
            },
        })
        initKeaTests()
        productSetupStatusLogic({ productKey: ProductKey.EXPERIMENTS }).mount()
        productSetupStatusLogic({ productKey: ProductKey.EXPERIMENTS }).actions.setDetectedStatus('has-data')
    })

    afterEach(() => cleanup())

    it.each<ProductSetupStatus>(['loading', 'needs-setup', 'waiting-for-data'])(
        'bypasses %s only while the configured flag is enabled',
        (status) => {
            const setup = productSetupStatusLogic({ productKey: ProductKey.EXPERIMENTS })
            setup.actions.setDetectedStatus('loading')
            setup.actions.setDetectedStatus(status)
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]: true })
            const { rerender } = render(
                <ProductEmptyStateGate
                    emptyState={{ ...emptyState, bypassFeatureFlag: FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD }}
                >
                    <div>the real scene</div>
                </ProductEmptyStateGate>
            )
            expect(screen.getByText('the real scene')).not.toBeNull()
            expect(noopStatusLogic.findMounted()).toBeNull()
            expect(setup.values.skipped).toBe(false)
            expect(setup.values.status).toBe(status)
            act(() => featureFlagLogic.actions.setFeatureFlags([], {}))
            expect(screen.queryByText('the real scene')).toBeNull()
            expect(noopStatusLogic.findMounted()).not.toBeNull()
            expect(setup.values.skipped).toBe(false)
            act(() =>
                featureFlagLogic.actions.setFeatureFlags([], {
                    [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]: true,
                })
            )
            rerender(
                <ProductEmptyStateGate emptyState={emptyState}>
                    <div>the real scene</div>
                </ProductEmptyStateGate>
            )
            expect(screen.queryByText('the real scene')).toBeNull()
        }
    )

    it('waits for the bypass flag before mounting detection', () => {
        productSetupStatusLogic({ productKey: ProductKey.EXPERIMENTS }).actions.setDetectedStatus('needs-setup')
        render(
            <ProductEmptyStateGate
                emptyState={{ ...emptyState, bypassFeatureFlag: FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD }}
            >
                <div>the real scene</div>
            </ProductEmptyStateGate>
        )
        expect(noopStatusLogic.findMounted()).toBeNull()
        expect(screen.queryByText('Set up experiments')).toBeNull()
        expect(screen.queryByText('the real scene')).toBeNull()
        act(() =>
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]: true })
        )
        expect(screen.getByText('the real scene')).not.toBeNull()
        expect(noopStatusLogic.findMounted()).toBeNull()
    })

    // `?empty_state` exists so anyone can review the setup screen on a project that already
    // has data. Matching it too loosely would hide a real scene from a normal URL, so the
    // off cases matter as much as the on ones.
    it.each([
        ['?empty_state=1', true],
        ['?empty_state', true],
        ['?empty_state=waiting-for-data', true],
        ['?empty_state=0', false],
        ['', false],
    ])('renders the setup screen for %s: %s', (search, expectedForced) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]: true })
        router.actions.push(`/experiments${search}`)

        render(
            <ProductEmptyStateGate
                emptyState={{ ...emptyState, bypassFeatureFlag: FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD }}
            >
                <div>the real scene</div>
            </ProductEmptyStateGate>
        )

        expect(!!screen.queryByText('Set up experiments')).toBe(expectedForced)
        expect(!!screen.queryByText('the real scene')).toBe(!expectedForced)
    })

    // One scene serves every workflows tab, so gating the scene would take the sibling tabs
    // down with it: a project with no workflows could not reach channels or opt-outs at all.
    it.each([
        [undefined, true],
        ['workflows', true],
        ['channels', false],
        ['opt-outs', false],
    ])('gates the %s tab: %s', (tab, expectedGated) => {
        const statusLogic = productSetupStatusLogic({ productKey: ProductKey.WORKFLOWS })
        statusLogic.mount()
        statusLogic.actions.setDetectedStatus('needs-setup')
        sceneLogic.mount()
        sceneLogic.actions.setScene(Scene.Workflows, undefined, { params: {}, searchParams: {}, hashParams: {} })

        render(
            <ProductEmptyStateGate emptyState={tabScopedEmptyState} params={{ tab }}>
                <div>the real scene</div>
            </ProductEmptyStateGate>
        )

        expect(!!screen.queryByText('Set up workflows')).toBe(expectedGated)
        expect(!!screen.queryByText('the real scene')).toBe(!expectedGated)
    })
})
