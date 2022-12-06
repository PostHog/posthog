describe('Person Visualization Check', () => {
    beforeEach(() => {
        cy.clickNavMenu('persons')
        cy.location('pathname').should('eq', '/persons')
        cy.get('.ant-spin-spinning').should('not.exist') // Wait until initial table load to be able to use the search
        cy.get('[data-attr=persons-search]').type('deb').should('have.value', 'deb')
        cy.contains('deborah.fernandez@gmail.com').should('not.exist')
        cy.contains('deborah.fernandez@gmail.com').click()
        cy.wait(1000)
    })

    it('Can access person page', () => {
        cy.get('[data-row-key="email"] > :nth-child(1)').should('contain', 'email')
        cy.get('[data-row-key="email"] .copy-icon').click()
        cy.get('[role="tab"]').contains('Events').click()
        cy.get('table').contains('Event').should('exist')
    })

    it('Does not show the Person column', () => {
        cy.get('[role="tab"]').contains('Events').click()
        cy.get('table').contains('Event').click()
        cy.get('table').should('not.contain', 'Person')
    })
})
