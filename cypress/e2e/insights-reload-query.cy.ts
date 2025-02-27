describe('ReloadInsight component', () => {
    beforeEach(() => {
        // Clear local storage before each test to ensure a clean state
        cy.clearLocalStorage()
    })

    it('saves the query to the URL and localStorage, and reloads it when prompted', () => {
        cy.intercept('POST', /api\/environments\/\d+\/query\//).as('loadNewQueryInsight')

        // Visit the new insight creation page
        cy.visit('/insights/new')

        cy.wait(2000)

        cy.get('[data-attr="math-selector-0"]').click({ force: true })
        cy.wait('@loadNewQueryInsight')
        cy.get('[data-attr="math-dau-0"]').click({ force: true })

        // Check that the 'draft-query' item is stored in localStorage
        cy.window().then((window) => {
            const currentTeamId = window.POSTHOG_APP_CONTEXT.current_team.id
            const draftQuery = window.localStorage.getItem(`draft-query-${currentTeamId}`)
            expect(draftQuery).to.not.be.null

            const draftQueryObj = JSON.parse(draftQuery)

            expect(draftQueryObj).to.have.property('query')

            const firstSeries = draftQueryObj.query.source.series[0]

            expect(firstSeries).to.include({
                event: '$pageview',
                math: 'dau',
            })
        })

        // Navigate away to the "Saved Insights" page
        cy.visit('/saved_insights')

        // Verify that the ReloadInsight component displays a message about the unsaved insight
        cy.contains('You have an unsaved insight from').should('exist')

        // Click the link to reload the unsaved insight
        cy.contains('Click here').click()

        cy.get('[data-attr="math-selector-0"]').should('contain', 'Unique users')
    })
})
