describe('Person Visualization Check', () => {
    beforeEach(() => {
        cy.clickNavMenu('persons')
        cy.location('pathname').should('eq', '/persons')
        cy.get('.ant-spin-spinning').should('not.exist') // Wait until initial table load to be able to use the search
        cy.get('[data-attr=persons-search]').type('deb').should('have.value', 'deb')
        cy.get('.ant-input-search-button').click()
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

describe('Merge person', () => {
    beforeEach(() => {
        cy.clickNavMenu('persons')
        cy.get('[data-attr=persons-search]').type('deb').should('have.value', 'deb')
        cy.get('.ant-input-search-button').click()
        cy.contains('deborah.fernandez@gmail.com').click()
        cy.wait(1000)
    })

    it('Should merge person', () => {
        cy.get('[role="tab"]').contains('Events').click()
        cy.get('.extra-ids').should('not.exist') // No extra IDs
        cy.contains('$create_alias').should('not.exist')
        cy.get('span.property-key-info:contains(Pageview)').should('have.length', 1)
        cy.get('span.property-key-info:contains(clicked)').should('have.length', 1)

        // Merge people
        cy.get('[data-attr=merge-person-button]').click()
        cy.get('.ant-select-multiple').type('merritt')
        cy.contains('merritt.humphrey@gmail.com').click()
        cy.contains('Merge persons').click()

        cy.contains('Automatically load new events').click()
        cy.get('.extra-ids').should('contain', '+1')
    })
})
