import { decideResponse } from '../fixtures/api/decide'

describe('Onboarding', () => {
    beforeEach(() => {
        cy.intercept('/api/billing/', { fixture: 'api/billing/billing-unsubscribed.json' })

        cy.intercept('**/decide/*', (req) =>
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

    // it('Step through PA onboarding', () => {
    //     cy.visit('/products')

    //     // Get started on product analytics onboarding
    //     cy.get('[data-attr=product_analytics-onboarding-card]').click()

    //     // Installation should be complete
    //     cy.get('svg.LemonIcon.text-success').should('exist')
    //     cy.get('svg.LemonIcon.text-success').parent().should('contain', 'Installation complete')

    //     // Continue to configuration step
    //     cy.get('[data-attr=sdk-continue]').click()

    //     // Confirm the appropriate breadcrumb is highlighted
    //     cy.get('[data-attr=onboarding-breadcrumbs] > :nth-child(3) > * span').should('contain', 'Configure')
    //     cy.get('[data-attr=onboarding-breadcrumbs] > :nth-child(3) > * span').should('not.have.css', 'text-muted')

    //     // Continue to plans
    //     cy.get('[data-attr=onboarding-continue]').click()

    //     // Verify pricing table visible
    //     cy.get('.BillingHero').should('be.visible')
    //     cy.get('table.PlanComparison').should('be.visible')

    //     // Confirm buttons on pricing comparison
    //     cy.get('[data-attr=upgrade-Paid] .LemonButton__content').should('have.text', 'Upgrade')
    //     cy.get('[data-attr=upgrade-Free] .LemonButton__content').should('have.text', 'Current plan')

    //     // Continue
    //     cy.get('[data-attr=onboarding-skip-button]').click()

    //     // Click back to Install step
    //     cy.get('[data-attr=onboarding-breadcrumbs] > :first-child > * span').click()

    //     // Continue through to finish
    //     cy.get('[data-attr=sdk-continue]').click()
    //     cy.get('[data-attr=onboarding-continue]').click()
    //     cy.get('[data-attr=onboarding-skip-button]').click()
    //     cy.get('[data-attr=onboarding-continue]').click()

    //     // Confirm we're on the insights list page
    //     cy.url().should('contain', 'project/1/insights')

    //     cy.visit('/onboarding/product_analytics?step=product_intro')

    //     // Should see both an option to skip onboarding and an option to see the sdk instructions
    //     cy.get('[data-attr=skip-onboarding]').should('be.visible')
    //     cy.get('[data-attr=start-onboarding-sdk]').should('be.visible')

    //     cy.get('[data-attr=skip-onboarding]').first().click()
    //     cy.url().should('contain', 'project/1/insights')

    //     cy.visit('/onboarding/product_analytics?step=product_intro')
    //     cy.get('[data-attr=start-onboarding-sdk]').first().click()
    //     cy.url().should('contain', 'project/1/onboarding/product_analytics?step=install')

    //     cy.visit('/products')
    //     cy.get('[data-attr=return-to-product_analytics] > svg').click()
    //     cy.url().should('contain', 'project/1/insights')
    // })

    // it('Step through SR onboarding', () => {
    //     cy.visit('/products')
    //     cy.get('[data-attr=session_replay-onboarding-card]').click()

    //     // Installation should be complete
    //     cy.get('svg.LemonIcon.text-success').should('exist')
    //     cy.get('svg.LemonIcon.text-success').parent().should('contain', 'Installation complete')
    //     // Continue to configuration step
    //     cy.get('[data-attr=sdk-continue]').click()
    //     // Continue to plans
    //     cy.get('[data-attr=onboarding-continue]').click()
    //     // Verify pricing table visible
    //     cy.get('.BillingHero').should('be.visible')
    //     cy.get('table.PlanComparison').should('be.visible')
    //     // Confirm buttons on pricing comparison
    //     cy.get('[data-attr=upgrade-Paid] .LemonButton__content').should('have.text', 'Upgrade')
    //     cy.get('[data-attr=upgrade-Free] .LemonButton__content').should('have.text', 'Current plan')
    //     // Continue through to finish
    //     cy.get('[data-attr=onboarding-skip-button]').click()
    //     cy.get('[data-attr=onboarding-continue]').click()
    //     // Confirm we're on the recordings list page
    //     cy.url().should('contain', 'project/1/replay/recent')
    //     cy.visit('/onboarding/session_replay?step=product_intro')
    //     cy.get('[data-attr=skip-onboarding]').should('be.visible')
    //     cy.get('[data-attr=start-onboarding-sdk]').should('not.exist')
    // })

    // it('Step through FF onboarding', () => {
    //     cy.visit('/onboarding/feature_flags?step=product_intro')
    //     cy.get('[data-attr=start-onboarding-sdk]').first().click()
    //     cy.get('[data-attr=sdk-continue]').click()

    //     // Confirm the appropriate breadcrumb is highlighted
    //     cy.get('[data-attr=onboarding-breadcrumbs] > :nth-child(5) > * span').should('contain', 'Plans')
    //     cy.get('[data-attr=onboarding-breadcrumbs] > :nth-child(3) > * span').should('not.have.css', 'text-muted')

    //     cy.get('[data-attr=onboarding-skip-button]').click()
    //     cy.get('[data-attr=onboarding-continue]').click()

    //     cy.url().should('contain', '/feature_flags')

    //     cy.visit('/onboarding/feature_flags?step=product_intro')

    //     cy.get('[data-attr=skip-onboarding]').should('be.visible')
    //     cy.get('[data-attr=start-onboarding-sdk]').should('be.visible')

    //     cy.get('[data-attr=skip-onboarding]').first().click()
    // })

    // it('Step through Surveys onboarding', () => {
    //     cy.visit('/onboarding/surveys?step=product_intro')
    //     cy.get('[data-attr=skip-onboarding]').should('be.visible')
    //     cy.get('[data-attr=start-onboarding-sdk]').should('not.exist')
    //     cy.get('[data-attr=skip-onboarding]').first().click()
    //     cy.url().should('contain', 'survey_templates')

    //     cy.visit('/products')
    //     cy.get('[data-attr=surveys-onboarding-card]').click()
    //     // Installation should be complete
    //     cy.get('svg.LemonIcon.text-success').should('exist')
    //     cy.get('svg.LemonIcon.text-success').parent().should('contain', 'Installation complete')

    //     // Continue to configuration step
    //     cy.get('[data-attr=sdk-continue]').click()

    //     // Verify pricing table visible
    //     cy.get('.BillingHero').should('be.visible')
    //     cy.get('table.PlanComparison').should('be.visible')

    //     // Confirm buttons on pricing comparison
    //     cy.get('[data-attr=upgrade-Paid] .LemonButton__content').should('have.text', 'Upgrade')
    //     cy.get('[data-attr=upgrade-Free] .LemonButton__content').should('have.text', 'Current plan')

    //     // Continue
    //     cy.get('[data-attr=onboarding-skip-button]').click()
    //     cy.get('[data-attr=onboarding-continue]').click()

    //     cy.url().should('contain', '/survey_templates')
    // })
})
