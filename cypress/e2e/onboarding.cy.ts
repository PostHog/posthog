import { setupFeatureFlags } from '../support/decide'

describe('Onboarding', () => {
    beforeEach(() => {
        cy.intercept('/api/billing/', { fixture: 'api/billing/billing-unsubscribed.json' })
        setupFeatureFlags({ 'product-intro-pages': 'test' })
    })

    it('Navigate between /products to /onboarding to a product intro page', () => {
        cy.visit('/products')

        // Get started on product analytics onboarding
        cy.get('[data-attr=product_analytics-onboarding-card]').click()

        // Click "Get started" button
        cy.get('[data-attr=onboarding-continue]').click()

        // Confirm product intro is not included as the first step in the upper right breadcrumbs
        cy.get('[data-attr=onboarding-breadcrumbs] > :first-child > * span').should('not.contain', 'Product intro')

        cy.window().then((win) => {
            win.POSTHOG_APP_CONTEXT.current_team.has_completed_onboarding_for = {}
        })

        cy.get('[data-attr=menu-item-savedinsights]').click()

        // Confirm we're on the product_intro page
        cy.get('[data-attr=top-bar-name] > span').contains('Onboarding')
        cy.get('[data-attr=product-intro-title]').contains('Product analytics with autocapture')

        cy.get('[data-attr=start-onboarding]').should('be.visible')
        cy.get('[data-attr=skip-onboarding]').should('not.exist')
    })
})
