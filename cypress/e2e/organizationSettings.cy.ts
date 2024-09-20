import { urls } from 'scenes/urls'

// For tests related to team members administration please see `inviteMembers.js`
describe('Organization settings', () => {
    beforeEach(() => {
        cy.intercept('/api/billing/', { fixture: 'api/billing/billing.json' })
        cy.useSubscriptionStatus('subscribed')
    })
    it('can navigate to organization settings', () => {
        cy.get('[data-attr=menu-item-me]').click()
        cy.get('[data-attr=top-menu-item-org-settings]').click()
        cy.location('pathname').should('include', '/settings/organization')
    })
    it('can create a new organization', () => {
        cy.visit(urls.settings('organization'), {
            onLoad(win: Cypress.AUTWindow) {
                ;(win as any).POSTHOG_APP_CONTEXT.preflight.cloud = true
            },
        })
        cy.get('[data-attr=breadcrumb-organization]').click()
        cy.get('[data-attr=new-organization-button]').click()
        cy.get('[data-attr=organization-name-input]').type('New Organization')
        cy.get('[data-attr=create-organization-ok]').click()
        cy.get('[data-attr=organization-name-input-settings]').should('have.value', 'New Organization')
    })
    it('can delete an organization', () => {
        cy.visit(urls.settings('organization'), {
            onLoad(win: Cypress.AUTWindow) {
                ;(win as any).POSTHOG_APP_CONTEXT.preflight.cloud = true
            },
        })
        cy.get('[data-attr=organization-name-input-settings]').should('have.value', 'New Organization')
        cy.get('[data-attr=delete-organization-button]').click()
        cy.get('[data-attr=delete-organization-confirmation-input]').type('New Organization')
        cy.get('[data-attr=delete-organization-ok]').click()
        // it redirects to the homepage after deleting the organization
        cy.get('[data-attr=organization-name-input-settings]').should('not.exist')
        cy.get('[data-attr=top-bar-name]').should('contain.text', 'Homepage')
    })
})
