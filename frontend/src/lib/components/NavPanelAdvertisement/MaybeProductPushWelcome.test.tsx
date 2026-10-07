import '@testing-library/jest-dom'

import { act, cleanup, render, waitFor } from '@testing-library/react'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { MaybeProductPushWelcome } from './MaybeProductPushWelcome'
import { navPanelProductPushWelcomeLogic } from './navPanelProductPushWelcomeLogic'
import type { PendingProductPushWelcome } from './navPanelProductPushWelcomeVisibility'

const WELCOME: PendingProductPushWelcome = {
    campaignId: 'campaign-1',
    productKey: ProductKey.PRODUCT_ANALYTICS,
    label: 'Product analytics',
    text: 'Insights, funnels, trends, and retention.',
}

describe('MaybeProductPushWelcome', () => {
    afterEach(() => cleanup())

    it('opens the pending welcome automatically when the scene releases its hold', async () => {
        initKeaTests()
        sceneLogic.mount()
        sceneLogic.actions.setExportedScene(
            { component: (): null => null, productKey: ProductKey.PRODUCT_ANALYTICS },
            Scene.SavedInsights,
            undefined,
            { params: {}, searchParams: {}, hashParams: {} }
        )
        const logic = navPanelProductPushWelcomeLogic()
        logic.mount()
        logic.actions.holdWelcome('first-run')
        logic.actions.setPendingWelcome(WELCOME)

        render(<MaybeProductPushWelcome />)
        expect(document.querySelector('[data-attr="product-push-welcome"]')).not.toBeInTheDocument()

        act(() => logic.actions.releaseWelcome('first-run'))

        await waitFor(() => expect(document.querySelector('[data-attr="product-push-welcome"]')).toBeInTheDocument())
    })
})
