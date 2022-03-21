describe('Insights Premium Features', () => {
    beforeEach(() => {
        cy.clickNavMenu('insight')
        cy.location('pathname').should('include', '/insights')
    })

    xit('Tag insight', () => {
        const newTag = `test-${Math.floor(Math.random() * 10000)}`
        cy.get('[data-attr=button-add-tag]').click()
        cy.focused().type(newTag)
        cy.get('[data-attr=new-tag-option]').click()
        cy.get('.ant-tag').should('contain', newTag)

        cy.wait(300)
        cy.get('.new-tag-input').should('not.exist') // Input should disappear
    })

    xit('Cannot add duplicate tags', () => {
        const newTag = `test2-${Math.floor(Math.random() * 10000)}`
        cy.get('[data-attr=button-add-tag]').click()
        cy.focused().type(newTag)
        cy.get('[data-attr=new-tag-option]').click()
        cy.get('.ant-tag').should('contain', newTag)

        cy.wait(300)
        cy.get('[data-attr=button-add-tag]').click()
        cy.focused().type(newTag)
        cy.get('[data-attr=new-tag-option]').click()
        cy.get('.Toastify__toast--error').should('be.visible')
    })
})
