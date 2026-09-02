import { cleanup, render, screen } from '@testing-library/react'
import { kea, path } from 'kea'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { ProductEmptyStateGate } from './ProductEmptyStateGate'
import { productSetupStatusLogic } from './productSetupStatusLogic'
import type { ProductEmptyStateConfig, SceneProductEmptyState } from './types'

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
        router.actions.push(`/experiments${search}`)

        render(
            <ProductEmptyStateGate emptyState={emptyState}>
                <div>the real scene</div>
            </ProductEmptyStateGate>
        )

        expect(!!screen.queryByText('Set up experiments')).toBe(expectedForced)
        expect(!!screen.queryByText('the real scene')).toBe(!expectedForced)
    })
})
