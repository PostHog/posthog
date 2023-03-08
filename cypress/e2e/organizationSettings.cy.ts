// For tests related to team members administration please see `inviteMembers.js`
describe('Organization settings', () => {
    it('can navigate to organization settings', () => {
        cy.get('[data-attr=top-menu-toggle]').click()
        cy.get('[data-attr=top-menu-item-org-settings]').click()
        cy.location('pathname').should('include', '/organization/settings')
        cy.get('.page-title').should('contain', 'Organization')
    })
})
