describe('Person Visualization Check', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-persons]').click()
        cy.get('.ant-spin-spinning').should('not.exist') // Wait until initial table load to be able to use the search
        cy.get('[data-attr=persons-search]').type('deb').should('have.value', 'deb')
        cy.get('.ant-input-search-button').click()
        cy.contains('deborah.fernandez@gmail.com').click()
    })

    it('Can access person page', () => {
        cy.get('[data-row-key="email"] > :nth-child(1)').should('contain', 'email')
    })

    it('Events table loads', () => {
        cy.get('.events').should('exist')
    })

    // Add when feature flag for session recording is off
    // it('Sessions table loads', () => {})
})

describe('Person Show All Distinct Checks', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-persons]').click()
        cy.get('.ant-spin-spinning').should('not.exist') // Wait until initial table load
    })

    it('Should have no Show All Distinct Id Button', () => {
        cy.get('[data-attr=persons-search]').type('fernand{enter}')
        cy.contains('deborah.fernandez@gmail.com').click()
        cy.get('[data-cy="show-more-distinct-id"]').should('not.exist')
    })
})
