describe('Signup', () => {
    beforeEach(() => {
        cy.get('[data-attr=top-menu-toggle]').click()
        cy.get('[data-attr=top-menu-item-logout]').click()
        cy.location('pathname').should('include', '/login')
        cy.visit('/signup')
    })

    it('Cannot create acount with existing email', () => {
        cy.get('[data-attr=signup-email]').type('test@posthog.com').should('have.value', 'test@posthog.com')
        cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')
        cy.get('[data-attr=signup-first-name]').type('Jane').should('have.value', 'Jane')
        cy.get('[data-attr=signup-organization-name]').type('Hogflix Movies').should('have.value', 'Hogflix Movies')
        cy.get('[data-attr=signup-submit]').click()

        cy.get('.ant-form-item-explain-error').should('contain', 'There is already an account with this email address.')
    })

    it('Cannot signup without required attributes', () => {
        cy.get('[data-attr=signup-submit]').click()
        cy.get('.ant-form-item-explain-error').should('contain', 'Please enter your email to continue')
        cy.get('.ant-form-item-explain-error').should('contain', 'Please enter your first name')
    })

    it('Cannot signup with invalid attributes', () => {
        cy.get('[data-attr=signup-email]').type('not an email')
        cy.get('[data-attr=password]').type('123').should('have.value', '123')
        cy.get('.ant-form-item-explain-error').should('not.exist') // Validation errors not shown until first submission
        cy.get('[data-attr=signup-submit]').click()
        cy.get('.ant-form-item-explain-error').should('contain', 'Please enter a valid email')
        cy.get('.ant-form-item-explain-error').should('contain', 'Passwords must be at least 8 characters')

        cy.get('[data-attr=password]').type('45678901')
        cy.get('.ant-form-item-explain-error').should('not.contain', 'Passwords must be at least 8 characters') // Validation error removed on keystroke
    })

    it('Can create user account', () => {
        const email = `new_user+${Math.floor(Math.random() * 10000)}@posthog.com`
        cy.get('[data-attr=signup-email]').type(email).should('have.value', email)
        cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')
        cy.get('[data-attr=signup-first-name]').type('Alice').should('have.value', 'Alice')
        cy.get('[data-attr=signup-organization-name]').type('Hogflix SpinOff').should('have.value', 'Hogflix SpinOff')
        cy.get('[data-attr=signup-submit]').click()

        cy.location('pathname').should('match', /(\/personalization)|(\/ingestion)/)
    })
})
