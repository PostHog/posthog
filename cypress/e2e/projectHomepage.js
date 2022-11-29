describe('Project Homepage', () => {
    beforeEach(() => {
        cy.intercept('GET', /\/api\/projects\/\d+\/dashboards\/\d+\//).as('getDashboard')
        cy.clickNavMenu('projecthomepage')
    })

    it('Shows home dashboard on load', () => {
        cy.wait('@getDashboard').its('response.statusCode').should('eq', 200)
        cy.verifyCallCount(`getDashboard`, 1) // Only loads once
        cy.get('[data-attr=insight-card]').its('length').should('be.gte', 1)
    })
})
