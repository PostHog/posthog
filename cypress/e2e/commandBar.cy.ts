describe('Command Bar', () => {
    it('Handles keyboard shortcuts', () => {
        /** Show/hide search */
        // show search
        cy.get('body').type('{ctrl}k')
        cy.get('[data-attr=search-bar-input]').should('exist')

        // TODO: fix hiding search with cmd+k
        // hide search with cmd+k
        // cy.get('body').type('{cmd}k')
        // cy.get('[data-attr=search-bar-input]').should('not.exist')

        // show search
        // cy.get('body').type('{ctrl}k')
        // cy.get('[data-attr=search-bar-input]').should('exist')

        // hide search with esc
        cy.get('body').type('{esc}')
        cy.get('[data-attr=search-bar-input]').should('not.exist')

        /** Show/hide actions */
        // show actions
        cy.get('body').type('{ctrl}{shift}k')
        cy.get('[data-attr=action-bar-input]').should('exist')

        // TODO: fix hiding actions with cmd+shift+k
        // hide actions with cmd+shift+k
        // cy.get('body').type('{ctrl}{cmd}k')
        // cy.get('[data-attr=action-bar-input]').should('not.exist')

        // // show actions
        // cy.get('body').type('{ctrl}{shift}k')
        // cy.get('[data-attr=action-bar-input]').should('exist')

        // hide actions with esc
        cy.get('body').type('{esc}')
        cy.get('[data-attr=action-bar-input]').should('not.exist')

        /** Show/hide shortcuts */
        // show shortcuts
        cy.get('body').type('{shift}?')
        cy.contains('Keyboard shortcuts').should('exist')

        // hide shortcuts with esc
        cy.get('body').type('{esc}')
        cy.contains('Keyboard shortcuts').should('not.exist')

        /** Toggle between search and actions */
        // TODO: does not work at the moment
    })
})
