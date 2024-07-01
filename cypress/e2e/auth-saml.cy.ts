const samlEmail = 'me@zlwaterfield.com'
const samlPassword = 'tg6tA8epnXy8edBL3hdr'

describe('SAML Auth', () => {
    beforeEach(() => {
        cy.get('[data-attr=menu-item-me]').click()
    })

    it('Login with SAML', () => {
        cy.get('[data-attr=top-menu-item-logout]').click()

        cy.get('[data-attr=login-email').type(samlEmail).should('have.value', samlEmail).blur()
        cy.wait(500)
        cy.get('[data-attr=password]').should('not.be.visible')
        cy.get('button[data-attr=sso-login]').should('have.text', 'Log in with Single sign-on (SAML)').click()

        cy.origin('https://trial-4372086.okta.com/app/trial-4372086_posthogdev_1/exkfso4f5a5yoH2u9697/sso/saml', () => {
            const samlEmail = 'me@zlwaterfield.com'
            const samlPassword = 'tg6tA8epnXy8edBL3hdr'
            cy.get('input[name=identifier]').type(samlEmail).should('have.value', samlEmail)
            cy.get('input[type=submit]').should('have.value', 'Next').click()
            cy.get('input[type=password]').type(samlPassword).should('have.value', samlPassword)
            cy.get('input[type=submit]').should('have.value', 'Verify').click()
        })

        cy.wait(10000)

        // cy.location('pathname', { timeout: 200000 }).should('eq', '/')
    })
})
