const UNSUBSCRIBE_SURVEY_ID = '018b6e13-590c-0000-decb-c727a2b3f462'

describe('Billing', () => {
    beforeEach(() => {
        cy.intercept('/api/billing/', { fixture: 'api/billing/billing.json' })

        cy.visit('/organization/billing')
    })

    it('Show and submit unsubscribe survey', () => {
        cy.intercept('/api/billing/deactivate?products=product_analytics', {
            fixture: 'api/billing/billing-unsubscribed-product-analytics.json',
        }).as('unsubscribeProductAnalytics')
        cy.visit('/organization/billing')

        cy.get('[data-attr=more-button]').first().click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('.LemonModal h3').should('contain', 'Unsubscribe from Product analytics')
        cy.get('[data-attr=unsubscribe-reason-too-expensive]').click()
        cy.get('[data-attr=unsubscribe-reason-survey-textarea]').type('Product analytics')
        cy.contains('.LemonModal .LemonButton', 'Unsubscribe').click()
        cy.window().then((win) => {
            const events = (win as any)._cypress_posthog_captures
            win.console.warn('_CYPRESS_POSTHOG_CAPTURES', JSON.stringify(events))
            const matchingEvents = events.filter((event) => event.event === 'survey sent')
            expect(matchingEvents.length).to.equal(1)
            const matchingEvent = matchingEvents[0]
            expect(matchingEvent.properties.$survey_id).to.equal(UNSUBSCRIBE_SURVEY_ID)
            expect(matchingEvent.properties.$survey_response).to.equal('Product analytics')
            expect(matchingEvent.properties.$survey_response_1).to.equal('product_analytics')
            expect(matchingEvent.properties.$survey_response_2.length).to.equal(1)
            expect(matchingEvent.properties.$survey_response_2[0]).to.equal('Too expensive')
        })

        cy.get('.LemonModal').should('not.exist')
        cy.wait(['@unsubscribeProductAnalytics'])
    })

    it('Unsubscribe survey text area maintains unique state between product types', () => {
        cy.get('[data-attr=more-button]').first().click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('.LemonModal h3').should('contain', 'Unsubscribe from Product analytics')

        cy.get('[data-attr=unsubscribe-reason-survey-textarea]').type('Product analytics')
        cy.contains('.LemonModal .LemonButton', 'Cancel').click()

        cy.get('[data-attr=more-button]').eq(1).click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('.LemonModal h3').should('contain', 'Unsubscribe from Session replay')
        cy.get('[data-attr=unsubscribe-reason-survey-textarea]').type('Session replay')
        cy.contains('.LemonModal .LemonButton', 'Cancel').click()

        cy.get('[data-attr=more-button]').first().click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('[data-attr=unsubscribe-reason-survey-textarea]').should('have.value', 'Product analytics')
    })
})
