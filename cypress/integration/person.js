describe('Person Visualization Check', () => {
    beforeEach(() => {
        cy.clickNavMenu('persons')
        cy.location('pathname').should('eq', '/persons')
        cy.get('.ant-spin-spinning').should('not.exist') // Wait until initial table load to be able to use the search
        cy.get('[data-attr=persons-search]').type('deb').should('have.value', 'deb')
        cy.get('.ant-input-search-button').click()
        cy.contains('deborah.fernandez@gmail.com').click()
    })

    it('Can access person page', () => {
        cy.get('[data-row-key="email"] > :nth-child(1)').should('contain', 'email')

        cy.get('.events').should('exist')
        cy.get('[data-attr="manage-events-table"] .ant-tabs-top').should('not.exist')
        cy.get('[data-row-key="email"] .copy-icon').click()
        cy.window()
            .then((win) => {
                const email = win.document.querySelector('[data-row-key="email"] .properties-table-value').textContent

                return [email, win]
            })
            .then((arr) => {
                arr[1].navigator.clipboard
                    .readText()
                    .then((copyText) => {
                        return [arr[0], copyText]
                    })
                    .then((array) => {
                        expect(array[0]).to.eq(array[1])
                    })
            })
    })
})

describe('Merge person', () => {
    beforeEach(() => {
        cy.clickNavMenu('persons')
        cy.get('[data-attr=persons-search]').type('deb').should('have.value', 'deb')
        cy.get('.ant-input-search-button').click()
        cy.contains('deborah.fernandez@gmail.com').click()
    })

    // Note: This test also checks that the plugin server has processed an event.
    it('Should merge person', () => {
        cy.get('.extra-ids').should('not.exist') // No extra IDs
        cy.contains('$create_alias').should('not.exist')
        cy.get('span:contains(Pageview)').should('have.length', 1)
        cy.get('span:contains(clicked)').should('have.length', 1)

        // Merge people
        cy.get('[data-attr=merge-person-button]').click()
        cy.get('.ant-select-multiple').type('merritt')
        cy.contains('merritt.humphrey@gmail.com').click()
        cy.contains('Merge persons').click()

        cy.contains('Automatically load new events').click()
        cy.contains('$create_alias', { timeout: 20000 }).should('exist')
        cy.get('span:contains(Pageview)').should('have.length', 2)
        cy.get('span:contains(clicked)').should('have.length', 2)
    })
})
