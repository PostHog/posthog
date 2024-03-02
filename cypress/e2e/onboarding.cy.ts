import { urls } from 'scenes/urls'
import { decideResponse } from '../fixtures/api/decide'

describe('Onboarding', () => {
    beforeEach(() => {
        cy.intercept('https://us.i.posthog.com/decide/*', (req) =>
            req.reply(
                decideResponse({
                    'product-intro-pages': 'test',
                })
            )
        )
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
        cy.get('[data-attr=product_analytics-onboarding-card]').click()

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

    it('Step through PA onboarding', () => {
        cy.visit('/products')

        // Get started on product analytics onboarding
        cy.get('[data-attr=product_analytics-onboarding-card]').click()

        // Installation should be complete
        cy.get('svg.LemonIcon.text-success').should('exist')
        cy.get('svg.LemonIcon.text-success').parent().should('contain', 'Installation complete')

        // Continue to configuration step
        cy.get('[data-attr=sdk-continue]').click()

        // Confirm the appropriate breadcrumb is highlighted
        cy.get('[data-attr=onboarding-breadcrumbs] > :nth-child(3) > * span').should('contain', 'Configure')
        cy.get('[data-attr=onboarding-breadcrumbs] > :nth-child(3) > * span').should('not.have.css', 'text-muted')

        // Continue to plans
        cy.get('[data-attr=onboarding-continue]').click()

        // Click show plans
        cy.get('[data-attr=show-plans]').click()

        // Verify pricing table visible
        cy.get('.BillingHero').should('be.visible')
        cy.get('table.PlanComparison').should('be.visible')

        // Continue
        cy.get('[data-attr=onboarding-continue]').click()

        // Click back to Install step
        cy.get('[data-attr=onboarding-breadcrumbs] > :first-child > * span').click()

        // Continue through to finish
        cy.get('[data-attr=sdk-continue]').click()
        cy.get('[data-attr=onboarding-continue]').click()
        cy.get('[data-attr=onboarding-continue]').click()
        cy.get('[data-attr=onboarding-continue]').click()

        // Confirm we're on the insights list page
        cy.url().should('contain', 'http://localhost:8080/project/1/insights')

        cy.visit('/onboarding/product_analytics?step=product_intro')

        // Should see both an option to skip onboarding and an option to see the sdk instructions
        cy.get('[data-attr=skip-onboarding]').should('be.visible')
        cy.get('[data-attr=start-onboarding-sdk]').should('be.visible')

        cy.get('[data-attr=skip-onboarding]').first().click()
        cy.url().should('contain', 'http://localhost:8080/project/1/insights')

        cy.visit('/onboarding/product_analytics?step=product_intro')
        cy.get('[data-attr=start-onboarding-sdk]').first().click()
        cy.url().should('contain', 'http://localhost:8080/project/1/onboarding/product_analytics?step=install')
    })

    it('Step through SR onboarding', () => {
        cy.get('[data-attr=menu-item-replay]').click()
        cy.get('[data-attr=start-onboarding]').first().click()
        // Installation should be complete
        cy.get('svg.LemonIcon.text-success').should('exist')
        cy.get('svg.LemonIcon.text-success').parent().should('contain', 'Installation complete')
        // Continue to configuration step
        cy.get('[data-attr=sdk-continue]').click()
        // Continue to plans
        cy.get('[data-attr=onboarding-continue]').click()
        // Go back to intro page
        cy.visit('/onboarding/session_replay?step=product_intro')
        // Continue through to finish
        cy.get('[data-attr=start-onboarding]').first().click()
        cy.get('[data-attr=sdk-continue]').click()
        cy.get('[data-attr=onboarding-continue]').click()
        cy.get('[data-attr=onboarding-continue]').click()
        // Confirm we're on the recordings list page
        cy.url().should('eq', 'https://localhost:8080/project/1/replay/recent')

        cy.visit('/onboarding/session_replay?step=product_intro')
        cy.get('[data-attr=skip-onboarding]').should('be.visible')
        cy.get('[data-attr=start-onboarding-sdk]').should('not.exist')
    })

    it('Step through FF onboarding', () => {
        cy.visit('/onboarding/feature_flags?step=product_intro')
        cy.get('[data-attr=menu-item-featureflags]').click()
        cy.get('[data-attr=start-onboarding-sdk]').first().click()
        cy.get('[data-attr=sdk-continue]').click()

        // Confirm the appropriate breadcrumb is highlighted
        cy.get('[data-attr=onboarding-breadcrumbs] > :nth-child(5) > * span').should('contain', 'Invite teammates')

        cy.visit('/onboarding/feature_flags?step=product_intro')

        cy.get('[data-attr=skip-onboarding]').should('be.visible')
        cy.get('[data-attr=start-onboarding-sdk]').should('be.visible')

        cy.get('[data-attr=skip-onboarding]').first().click()
        cy.url().should('contain', 'feature_flags/new')
    })

    it('Step through Surveys onboarding', () => {
        cy.visit('/onboarding/surveys?step=product_intro')
        cy.get('[data-attr=skip-onboarding]').should('be.visible')
        cy.get('[data-attr=start-onboarding-sdk]').should('not.exist')
        cy.get('[data-attr=skip-onboarding]').first().click()
        cy.url().should('contain', 'survey_templates')
    })
})
