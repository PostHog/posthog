describe('Invite Signup', () => {
    beforeEach(() => {
        cy.get('[data-attr=top-navigation-whoami]').click()
        cy.get('[data-attr=top-menu-item-org-settings]').click()

        cy.location('pathname').should('eq', '/organization/settings')
        cy.get('[data-attr=invite-teammate-button]').click({ force: true }) // The button gets nested under some weird Ant divs

        cy.get('[data-attr=invite-email-input]').type('newuser@posthog.com').should('have.value', 'newuser@posthog.com')
        cy.get('[data-attr=invite-team-member-submit]').click()

        cy.get('[data-attr=invites-table] tbody td').should('contain', 'newuser@posthog.com')
    })

    it('Authenticated user cannot use invite for someone else', () => {
        // Tests invite creation flow too
        cy.get('[data-attr=invites-table] tbody tr:last-of-type td:nth-last-child(2)').then((element) => {
            cy.visit(element.text())
        })
        cy.get('.error-view-container').should('exist')
        cy.get('h1.page-title').should('contain', 'Oops! You cannot use this invite link')
        cy.get('.error-message div').should('contain', 'This invite is intended for another email address')

        // Delete the invite
        cy.visit('/organization/members')
        cy.get('[data-attr=invites-table] .anticon-delete').click()
        cy.get('.ant-modal-confirm-btns button').contains('Delete').click()
    })

    it('New user can use invite', () => {
        cy.get('[data-attr=invites-table] tbody td:nth-last-child(2)').then((element) => {
            cy.get('[data-attr=top-navigation-whoami]').click()
            cy.get('[data-attr=top-menu-item-logout]').click()
            cy.visit(element.text())
        })
        cy.get('.error-view-container').should('not.exist')
        cy.get('h1.page-title').should('contain', "You've been invited to join")
        cy.get('#email').should('have.value', 'n*****r@posthog.com')
        cy.get('#password').type('12345678')
        cy.get('.ant-progress-bg').should('not.have.css', 'width', '0px') // Password strength indicator is working
        cy.get('#first_name').type('Bob')
        cy.get('[data-attr=password-signup]').click()
        cy.get('.Toastify__toast-body').should('contain', 'You have joined')
        cy.location('pathname').should('include', '/insights')
    })
})

describe('Invite Signup II', () => {
    it('Can leave the organization', () => {
        // Logout & log in with alt user
        cy.visit('/logout')
        cy.get('[data-attr=login-email]').type('newuser@posthog.com')
        cy.get('[data-attr=password]').type('12345678')
        cy.get('button[type=submit]').click()
        cy.location('pathname').should('not.eq', '/login') // Wait until login request fully completes

        // Leave current organization
        cy.visit('/organization/members')
        cy.get('[data-attr=org-members-table] .anticon-logout').click()
        cy.get('.ant-modal-confirm-btns button').contains('Leave').click()
        cy.location('pathname').should('include', '/organization/create')
    })
})
