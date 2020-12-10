describe('Person Visualization Check', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-people]').click() // TODO: Adjust when releasing navigation-1775
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
        cy.get('[data-attr=menu-item-people]').click()
    })

    it('Should have Show All Distinct Id Button', () => {
        cy.get('.ant-input').type('smith.nunez@gmail.com').type('{enter}')

        cy.contains('smith.nunez@gmail.com').click()
        cy.get('[data-cy="show-more-distinct-id"]').should('exist')
        cy.get('[data-cy="show-more-distinct-id"]').click()
    })

    it('Should have no Show All Distinct Id Button', () => {
        cy.contains('deborah.fernandez@gmail.com').click()
        cy.get('[data-cy="show-more-distinct-id"]').should('not.exist')
    })
})
