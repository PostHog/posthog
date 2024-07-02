describe('SAML Auth', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-me]').click()
    })

    it('Login with SAML', () => {
        cy.get('[data-attr=top-menu-item-logout]').click()

        cy.get('[data-attr=login-email').type('').should('have.value', '').blur()
        cy.wait(500)
        cy.get('[data-attr=password]').should('not.be.visible')
        cy.get('button[data-attr=sso-login]').should('have.text', 'Log in with Single sign-on (SAML)').click()

        cy.origin('https://trial-4372086.okta.com/app/trial-4372086_posthogdev_1/exkfso4f5a5yoH2u9697/sso/saml', () => {
            cy.get('input[name=identifier]').type('').should('have.value', '')
            cy.get('input[type=submit]').should('have.value', 'Next').click()
            cy.get('input[type=password]').type('').should('have.value', '')
            cy.get('input[type=submit]').should('have.value', 'Verify').click()
        })

        cy.wait(10000)

        // cy.location('pathname', { timeout: 200000 }).should('eq', '/')
    })
})
