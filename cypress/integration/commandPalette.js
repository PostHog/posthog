describe('Command Palette', () => {
    beforeEach(() => {
        cy.visit('/events')
    })

    it('Shows on toggle button click', () => {
        cy.get('[data-attr=command-palette-toggle]').click()
        cy.get('[data-attr=command-palette-input]').should('exist')
    })

    it('Shows on Ctrl + K press', () => {
        cy.get('body').type('{ctrl}C')
        cy.get('[data-attr=command-palette-input]').should('exist')
        cy.get('body').type('{cmd}C')
        cy.get('[data-attr=command-palette-input]').should('not.exist')
    })
})
