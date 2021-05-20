describe('Command Palette', () => {
    it('Shows on toggle button click', () => {
        cy.get('[data-attr=command-palette-toggle]').click()
        cy.get('[data-attr=command-palette-input]').should('exist')
    })

    it('Shows on Ctrl + K press', () => {
        cy.get('[data-attr=insight-trends-tab]').contains('Trends') // Make sure the page is loaded
        cy.get('body').type('{ctrl}k')
        cy.get('[data-attr=command-palette-input]').should('exist')

        cy.get('body').type('{cmd}k')
        cy.get('[data-attr=command-palette-input]').should('not.exist')
    })
})
