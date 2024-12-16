describe('ReloadInsight component', () => {
    beforeEach(() => {
        // Clear local storage before each test to ensure a clean state
        cy.clearLocalStorage()
    })

    it('saves the query to the URL and localStorage, and reloads it when prompted', () => {
        // Visit the new insight creation page
        cy.visit('/insights/new')

        // Interact with the page to change the query
        // For this example, we'll select the "Trends" insight and add an event
        cy.get('[data-attr="insight-type-selector"]').click()
        cy.contains('Trends').click()

        // Ensure the trends tab is active
        cy.get('[data-attr="insight-type-tab"]').should('have.class', 'active').and('contain', 'Trends')

        // Add an event to the query
        cy.get('[data-attr="add-event-button"]').click()
        cy.get('[data-attr="event-name-input"]').type('Pageview{enter}')

        // Wait for the query to run and results to load
        cy.get('.insights-graph-container').should('exist')

        // Verify that the URL contains the updated query in the hash parameters (e.g., 'q=')
        cy.location().then((location) => {
            expect(location.hash).to.contain('q=')
        })

        // Check that the 'draft-query' item is stored in localStorage
        cy.window().then((window) => {
            const draftQuery = window.localStorage.getItem('draft-query')
            expect(draftQuery).to.not.be.null

            const draftQueryObj = JSON.parse(draftQuery)
            expect(draftQueryObj).to.have.property('query')

            // Optional: Verify the content of the query matches the changes made
            expect(draftQueryObj.query).to.deep.include({
                kind: 'TrendsQuery',
                events: [{ id: 'Pageview' }],
            })
        })

        // Navigate away to the "Saved Insights" page
        cy.visit('/saved_insights')

        // Verify that the ReloadInsight component displays a message about the unsaved insight
        cy.contains('You have an unsaved insight from').should('exist')

        // Click the link to reload the unsaved insight
        cy.contains('Click here').click()

        // Confirm that we are redirected back to the insight creation page
        cy.location('pathname').should('eq', '/insights/new')

        // Verify that the query editor has restored the previous query
        // Check that "Pageview" is selected in the events
        cy.get('[data-attr="event-name"]').should('contain', 'Pageview')

        // Verify that the insights graph is displayed based on the restored query
        cy.get('.insights-graph-container').should('exist')
    })
})
