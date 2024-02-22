import { urls } from 'scenes/urls'
import { decideResponse } from '../fixtures/api/decide'

describe('Onboarding', () => {
    beforeEach(() => {
        cy.intercept('https://app.posthog.com/decide/*', (req) =>
            req.reply(
                decideResponse({
                    'product-intro-pages': 'test',
                })
            )
        )
    })

    it('Navigate between /products to /onboarding to a product intro page', () => {
        cy.visit('/products')

        // Get started on product analytics onboarding
        cy.get('[data-attr=product_analytics-get-started-button]').click()

        // Confirm product intro is not included as the first step in the upper right breadcrumbs
        cy.get('[data-attr=onboarding-breadcrumbs] > :first-child > * span').should('not.contain', 'Product Intro')

        // Navigate to the product intro page by clicking the left side bar
        cy.get('[data-attr=menu-item-replay').click()

        // Confirm we're on the product_intro page
        cy.get('[data-attr=top-bar-name] > span').contains('Product intro')

        // Go back to /products
        cy.visit('/products')

        // Again get started on product analytics onboarding
        cy.get('[data-attr=product_analytics-get-started-button]').click()

        // Navigate to the product intro page by changing the url
        cy.visit(urls.onboarding('session_replay', 'product_intro'))

        // Confirm we're on the product intro page
        cy.get('[data-attr=top-bar-name] > span').contains('Product intro')
    })
})
