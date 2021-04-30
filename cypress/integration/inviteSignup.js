describe('Invite Signup', () => {
    it('Authenticated user can invite user but cannot use invite for someone else', () => {
        cy.get('[data-attr=top-navigation-whoami]').click()
        cy.get('[data-attr=top-menu-item-org-settings]').click()

        cy.location('pathname').should('eq', '/organization/settings')
        cy.get('h2').contains('Pending Invites').should('exist')

        // Test invite creation flow
        cy.get('[data-attr=invites-table] [data-attr=invite-teammate-button]').click()
        cy.get('[data-attr=invite-email-input]').type('charlie@posthog.com').should('have.value', 'charlie@posthog.com')
        cy.get('[data-attr=invite-team-member-submit]').click()
        cy.get('[data-attr=invites-table] tbody td').should('contain', 'charlie@posthog.com')

        // Assert user cannot use invite for someone else
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
        cy.get('.Toastify__toast-body').should('contain', 'removed')
        cy.get('[data-attr=invites-table] tbody td').should('not.contain', 'charlie@posthog.com')
    })

    it('New user can use invite', () => {
        const target_email = `newuser+${Math.floor(Math.random() * 10000)}@posthog.com`
        cy.request({
            method: 'POST',
            url: '/api/organizations/@current/invites/',
            body: { target_email: target_email },
            headers: { Authorization: 'Bearer e2e_demo_api_key' },
        }).then((response) => {
            expect(response.status).to.eq(201)
            cy.get('[data-attr=top-navigation-whoami]').click()
            cy.get('[data-attr=top-menu-item-logout]').click()
            cy.visit('/signup/' + response.body.id)
        })
        cy.get('.error-view-container').should('not.exist')
        cy.get('h1.page-title').should('contain', "You've been invited to join")
        cy.get('#email').should('have.value', `n**********${target_email[11]}@posthog.com`)
        cy.get('#password').type('12345678')
        cy.get('.ant-progress-bg').should('not.have.css', 'width', '0px') // Password strength indicator is working
        cy.get('#first_name').type('Bob')
        cy.get('[data-attr=password-signup]').click()
        cy.get('.Toastify__toast-body').should('contain', 'You have joined')
        cy.location('pathname').should('include', '/insights')
    })
})
