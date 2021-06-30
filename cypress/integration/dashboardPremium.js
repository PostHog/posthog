describe('Dashboards Premium Features', () => {
    beforeEach(() => {
        cy.clickNavMenu('dashboards')
        cy.location('pathname').should('include', '/dashboard')
    })

    it('Tag dashboard', () => {
        const newTag = `test-${Math.floor(Math.random() * 10000)}`
        cy.get('[data-attr=dashboard-name]').contains('App Analytics').click()
        cy.get('[data-attr=button-add-tag]').click()
        cy.focused().type(newTag)
        cy.get('[data-attr=new-tag-option]').click()
        cy.get('.ant-tag').should('contain', newTag)

        cy.wait(300)
        cy.get('.new-tag-input').should('not.exist') // Input should disappear

        cy.clickNavMenu('dashboards')
        cy.get('.ant-tag').should('contain', newTag) // Tag is shown in dashboard list too
    })

    it('Cannot add duplicate tags', () => {
        const newTag = `test2-${Math.floor(Math.random() * 10000)}`
        cy.get('[data-attr=dashboard-name]').contains('App Analytics').click()
        cy.get('[data-attr=button-add-tag]').click()
        cy.focused().type(newTag)
        cy.get('[data-attr=new-tag-option]').click()
        cy.get('.ant-tag').should('contain', newTag)

        cy.wait(300)
        cy.get('[data-attr=button-add-tag]').click()
        cy.focused().type(newTag)
        cy.get('[data-attr=new-tag-option]').click()
        cy.get('.Toastify__toast--error').should('be.visible')

        cy.get('.dashboard').find('.ant-tag').contains(newTag).should('have.length', 1)
    })
})
