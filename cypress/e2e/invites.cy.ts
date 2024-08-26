import { auth } from '../productAnalytics'
import { randomString } from '../support/random'

const VALID_PASSWORD = 'hedgE-hog-123%'

describe('Invite Signup', () => {
    it('Authenticated user can invite user but cannot use invite for someone else', () => {
        const user = randomString('user-charlie-')
        const email = `${user}@posthog.com`

        cy.get('[data-attr=menu-item-me]').click()
        cy.get('[data-attr=top-menu-item-org-settings]').click()

        cy.location('pathname').should('contain', '/settings/organization')
        cy.get('[id="invites"]').should('exist')
        cy.contains('Pending invites').should('exist')

        // Test invite creation flow
        cy.get('[data-attr=invite-teammate-button]').click()
        cy.get('[data-attr=invite-email-input]').type(email).should('have.value', email)
        cy.get('[data-attr=invite-team-member-submit]').click()
        cy.get('[data-attr=invites-table] tbody td').should('contain', email)

        // Assert user cannot use invite for someone else
        cy.get('[data-attr=invites-table] tbody tr:last-of-type td:nth-last-child(2)').then((element) => {
            cy.visit(element.text())
        })
        cy.get('h2').should('contain', "Oops! This invite link can't be used")
        cy.get('.error-message div').should('contain', 'This invite is intended for another email address')

        // Delete the invite
        cy.visit('/organization/members')
        cy.get('[data-attr=invites-table] [data-attr=invite-delete]').first().click()
        cy.get('.LemonModal .LemonButton').contains('Yes, cancel invite').click()
        cy.get('.Toastify__toast-body').should('contain', `Invite for ${email} has been canceled`)
        cy.get('[data-attr=invites-table] tbody td').should('not.contain', email)
    })

    it('New user can use invite', () => {
        const target_email = `newuser+${Math.floor(Math.random() * 10000)
            .toString()
            // Ensure we have a fixed width
            .padStart(4, '0')}@posthog.com`
        cy.request({
            method: 'POST',
            url: '/api/organizations/@current/invites/',
            body: { target_email: target_email },
            headers: { Authorization: 'Bearer e2e_demo_api_key' },
        }).then((response) => {
            expect(response.status).to.eq(201)
            auth.logout()
            cy.visit('/signup/' + response.body.id)
        })
        cy.get('.error-view-container').should('not.exist')
        cy.get('.BridgePage__left').should('contain', "You've been invited to join")
        cy.get('input[type="email"]').should('have.value', target_email)
        cy.get('[data-attr="password"]').type(VALID_PASSWORD)
        cy.get('.LemonProgress__track').should('not.have.css', 'width', '0px') // Password strength indicator is working
        cy.get('[data-attr="first_name"]').type(randomString('Bob'))
        cy.get('[data-attr=signup-role-at-organization]').click()
        cy.get('.Popover li:first-child').click()
        cy.get('[data-attr=signup-role-at-organization]').contains('Engineering')
        cy.get('[data-attr=password-signup]').click()
        cy.location('pathname').should('include', 'verify_email')
    })

    it('can navigate to organization settings and invite/change users', () => {
        const user = randomString('user-bob-')

        cy.get('[data-attr=menu-item-me]').click()
        cy.get('[data-attr=top-menu-item-org-settings]').click()
        cy.location('pathname').should('include', '/settings/organization')

        // Click "Invite team member"
        cy.get('[data-attr=invite-teammate-button]').first().click()
        // Enter invite the user
        cy.get('[data-attr=invite-email-input]').type(`fake+${Math.floor(Math.random() * 10000)}@posthog.com`)
        cy.get('[data-attr=invite-team-member-submit]').should('not.be.disabled').click()

        // Log in as invited user
        cy.get('[data-attr=invite-link]')
            .last()
            .then((element) => {
                auth.logout()
                cy.visit(element.text())
            })
        cy.get('[data-attr="password"]').type(VALID_PASSWORD)
        cy.get('[data-attr="first_name"]').type(user)
        cy.get('[data-attr=signup-role-at-organization]').click()
        cy.get('.Popover li:first-child').click()
        cy.get('[data-attr=signup-role-at-organization]').contains('Engineering')
        cy.get('[data-attr=password-signup]').click()
        cy.location('pathname').should('include', 'verify_email')

        // Log out, log in as main
        auth.logout()
        cy.login()

        // Go to organization settings
        cy.get('[data-attr=menu-item-me]').click()
        cy.get('[data-attr=top-menu-item-org-settings]').click()
        cy.location('pathname').should('include', '/settings/organization')

        // Change membership level
        cy.contains('[data-attr=org-members-table] tr', user).within(() => {
            cy.get('[data-attr=membership-level]').last().should('contain', 'Member')
            cy.get('[data-attr=more-button]').last().click()
        })

        // more menu is not within the row
        cy.get('[data-test-level=8]').click()

        cy.contains('[data-attr=org-members-table] tr', user).within(() => {
            cy.get('[data-attr=membership-level]').last().should('contain', 'Admin')
        })

        // Delete member
        cy.contains('[data-attr=org-members-table] tr', user).within(() => {
            cy.get('[data-attr=more-button]').last().click()
        })

        // more menu is not within the row
        cy.get('[data-attr=delete-org-membership]').last().click()

        cy.get('.LemonModal .LemonButton').last().click()
        cy.get('.Toastify__toast-body').should('contain', `Removed ${user} from organization`)
    })
})
