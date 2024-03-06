import * as fflate from 'fflate'

const UNSUBSCRIBE_SURVEY_ID = '018b6e13-590c-0000-decb-c727a2b3f462'

describe('Billing', () => {
    beforeEach(() => {
        cy.intercept('/api/billing-v2/', { fixture: 'api/billing-v2/billing-v2.json' })

        cy.intercept('POST', '**/e/?compression=gzip-js*').as('capture')

        cy.visit('/organization/billing')
    })

    it('Show and submit unsubscribe survey', () => {
        cy.intercept('/api/billing-v2/deactivate?products=product_analytics', {
            fixture: 'api/billing-v2/billing-v2-unsubscribed-product-analytics.json',
        }).as('unsubscribeProductAnalytics')

        cy.get('[data-attr=more-button]').first().click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('.LemonModal h3').should('contain', 'Why are you unsubscribing from Product analytics + data stack?')
        cy.get('[data-attr=unsubscribe-reason-survey-textarea]').type('Product analytics')
        cy.contains('.LemonModal .LemonButton', 'Unsubscribe').click()

        cy.wait('@capture').then(({ request }) => {
            const data = new Uint8Array(request.body)
            const decoded = fflate.strFromU8(fflate.decompressSync(data))
            const decodedJSON = JSON.parse(decoded)

            // These should be a 'survey sent' event somewhere in the decodedJSON
            const matchingEvents = decodedJSON.filter((event) => event.event === 'survey sent')
            expect(matchingEvents.length).to.equal(1)
            const matchingEvent = matchingEvents[0]
            expect(matchingEvent.properties.$survey_id).to.equal(UNSUBSCRIBE_SURVEY_ID)
            expect(matchingEvent.properties.$survey_response).to.equal('Product analytics')
            expect(matchingEvent.properties.$survey_response_1).to.equal('product_analytics')
        })
        cy.get('.LemonModal').should('not.exist')
        cy.wait(['@unsubscribeProductAnalytics'])
    })

    it('Unsubscribe survey text area maintains unique state between product types', () => {
        cy.get('[data-attr=more-button]').first().click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('.LemonModal h3').should('contain', 'Why are you unsubscribing from Product analytics + data stack?')

        cy.get('[data-attr=unsubscribe-reason-survey-textarea]').type('Product analytics')
        cy.contains('.LemonModal .LemonButton', 'Cancel').click()

        cy.get('[data-attr=more-button]').eq(1).click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('.LemonModal h3').should('contain', 'Why are you unsubscribing from Session replay?')
        cy.get('[data-attr=unsubscribe-reason-survey-textarea]').type('Session replay')
        cy.contains('.LemonModal .LemonButton', 'Cancel').click()

        cy.get('[data-attr=more-button]').first().click()
        cy.contains('.LemonButton', 'Unsubscribe').click()
        cy.get('[data-attr=unsubscribe-reason-survey-textarea]').should('have.value', 'Product analytics')
    })
})
