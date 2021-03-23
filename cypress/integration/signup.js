describe('Signup', () => {
    beforeEach(() => {
        cy.get('[data-attr=top-navigation-whoami]').click()
        cy.get('[data-attr=top-menu-item-logout]').click()
        cy.location('pathname').should('include', '/login')
        cy.visit('/signup')
    })

    it('Cannot create acount with existing email', () => {
        cy.get('[data-attr=signup-email]').type('test@posthog.com').should('have.value', 'test@posthog.com')
        cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')
        cy.get('[data-attr=signup-continue]').click()

        cy.get('[data-attr=signup-first-name]').type('Jane').should('have.value', 'Jane')
        cy.get('[data-attr=signup-organization-name]').type('Hogflix Movies').should('have.value', 'Hogflix Movies')
        cy.get('[data-attr=signup-submit]').click()

        cy.get('[data-attr=signup-email]').should('be.visible') // we should be back at step 1
        cy.get('.ant-form-item-explain-error').should('contain', 'There is already an account with this email address.')
    })

    it('Cannot signup with required attributes', () => {
        cy.get('[data-attr=signup-continue]').click()

        cy.get('[data-attr=signup-first-name]').should('not.be.visible')
        cy.get('[data-attr=signup-email]').should('be.visible') // still in step 1

        cy.get('.ant-form-item-explain-error').should('contain', 'Please enter your email to continue')
        cy.get('.ant-form-item-explain-error').should('contain', 'Please enter your password to continue')
    })

    it('Can create user account', () => {
        const email = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        cy.get('[data-attr=signup-email]').type(email).should('have.value', email)
        cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')
        cy.get('[data-attr=signup-continue]').click()

        cy.get('[data-attr=signup-first-name]').type('Alice').should('have.value', 'Alice')
        cy.get('[data-attr=signup-organization-name]').type('Hogflix SpinOff').should('have.value', 'Hogflix SpinOff')
        cy.get('[data-attr=signup-submit]').click()

        cy.location('pathname').should('include', '/personalization')
        cy.get('[data-attr=radio-select-personalization-role]').should('be.visible')
    })
})
