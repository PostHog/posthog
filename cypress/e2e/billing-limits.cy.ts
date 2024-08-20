describe('Billing Limits', () => {
    it('Show no limits set and allow user to set one', () => {
        cy.intercept('GET', '/api/billing/', { fixture: 'api/billing/billing.json' }).as('getBilling')
        cy.visit('/organization/billing')
        cy.wait('@getBilling')

        cy.intercept('PATCH', '/api/billing/', (req) => {
            req.reply({
                statusCode: 200,
                body: {
                    ...require('../fixtures/api/billing/billing.json'),
                    custom_limits_usd: { product_analytics: 100 },
                },
            })
        }).as('patchBilling')

        cy.get('[data-attr="billing-limit-input-wrapper-product_analytics"]').scrollIntoView()
        cy.get('[data-attr="billing-limit-not-set-product_analytics"]').should('be.visible')
        cy.contains('Set a billing limit').click()
        cy.get('[data-attr="billing-limit-input-product_analytics"]').clear().type('100')
        cy.get('[data-attr="save-billing-limit-product_analytics"]').click()
        cy.wait('@patchBilling')
        cy.get('[data-attr="billing-limit-set-product_analytics"]').should(
            'contain',
            'You have a $100 billing limit set'
        )
    })

    it('Show existing limit and allow user to change it', () => {
        cy.intercept('GET', '/api/billing/', (req) => {
            req.reply({
                statusCode: 200,
                body: {
                    ...require('../fixtures/api/billing/billing.json'),
                    custom_limits_usd: { product_analytics: 100 },
                },
            })
        }).as('getBilling')
        cy.visit('/organization/billing')
        cy.wait('@getBilling')

        cy.intercept('PATCH', '/api/billing/', (req) => {
            req.reply({
                statusCode: 200,
                body: {
                    ...require('../fixtures/api/billing/billing.json'),
                    custom_limits_usd: { product_analytics: 200 },
                },
            })
        }).as('patchBilling')

        cy.get('[data-attr="billing-limit-input-wrapper-product_analytics"]').scrollIntoView()
        cy.get('[data-attr="billing-limit-set-product_analytics"]').should('be.visible')
        cy.contains('Edit limit').click()
        cy.get('[data-attr="billing-limit-input-product_analytics"]').clear().type('200')
        cy.get('[data-attr="save-billing-limit-product_analytics"]').click()
        cy.wait('@patchBilling')
        cy.get('[data-attr="billing-limit-set-product_analytics"]').should(
            'contain',
            'You have a $200 billing limit set'
        )
    })

    it('Show existing limit and allow user to remove it', () => {
        cy.intercept('GET', '/api/billing/', (req) => {
            req.reply({
                statusCode: 200,
                body: {
                    ...require('../fixtures/api/billing/billing.json'),
                    custom_limits_usd: { product_analytics: 100 },
                },
            })
        }).as('getBilling')
        cy.visit('/organization/billing')
        cy.wait('@getBilling')

        cy.intercept('PATCH', '/api/billing/', { fixture: 'api/billing/billing.json' }).as('patchBilling')

        cy.get('[data-attr="billing-limit-input-wrapper-product_analytics"]').scrollIntoView()
        cy.get('[data-attr="billing-limit-set-product_analytics"]').should('be.visible')
        cy.contains('Edit limit').click()
        cy.get('[data-attr="remove-billing-limit-product_analytics"]').click()
        cy.get('[data-attr="billing-limit-not-set-product_analytics"]').should('be.visible')
    })
})
