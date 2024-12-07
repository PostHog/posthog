describe('Data pipeline', () => {
    beforeEach(() => {
        cy.intercept('/api/billing/', { fixture: 'api/billing/billing-subscribed-all.json' })
        cy.clickNavMenu('pipeline')
    })

    it('shows get started state on first load', () => {
        cy.get('h1').should('contain', 'Overview')
        cy.title().should('equal', 'Overview • Data pipeline • PostHog')

        cy.contains('div', 'Destinations').click()
        cy.get('h1').should('contain', 'Destinations')
        cy.title().should('equal', 'Destinations • Data pipeline • PostHog')

        cy.contains('Create your first destination').should('exist')

        // create a new webhook destination
        cy.get('[data-attr="new-destination"]').eq(0).click()
        cy.wait(1000)
        cy.get('.LemonInput--type-search > input[placeholder="Search..."]').focus().type('Webhook')
        cy.get('[data-attr="new-destination"]').click()

        // inputs webhookUrl and saves
        cy.get('.monaco-editor').eq(0).type('https://example.com')
        cy.get('button[type="submit"]').eq(0).click()
        cy.get('[data-attr=success-toast]').contains('Configuration saved').should('exist')
    })

    it('connect hubspot account', () => {
        cy.get('h1').should('contain', 'Overview')
        cy.title().should('equal', 'Overview • Data pipeline • PostHog')

        cy.contains('div', 'Destinations').click()
        cy.get('h1').should('contain', 'Destinations')
        cy.title().should('equal', 'Destinations • Data pipeline • PostHog')

        // create a new webhook destination
        cy.get('[data-attr="new-destination"]').eq(0).click()
        cy.wait(1000) // not sure why this is needed
        cy.get('.LemonInput--type-search > input[placeholder="Search..."]').focus().type('Hubspot')
        cy.get('[data-attr="new-destination"]').eq(0).click()

        // inputs webhookUrl and saves
        cy.contains('Choose Hubspot connection').click()
        cy.contains('Connect to hubspot').click()

        cy.origin('app.hubspot.com', () => {
            const email = ''
            const password = ''
            const TOTPSecret = ''
            // ignore errors on on app.hubspot.com
            Cypress.on('uncaught:exception', () => false)

            // login
            cy.contains('Sign in to your HubSpot account').click()
            cy.get('input#username').type(email)
            cy.get('button#loginBtn').click()
            cy.get('input#current-password').type(password)
            cy.get('button#loginBtn').click()

            // 2fa step
            cy.task("generateOTP", TOTPSecret).then((token: string) => {
              cy.get('input#code').type(token)
            });
            cy.get('button[type="submit"]').click()
            cy.get('button[data-2fa-rememberme="false"]').click()

            // select account and confirm
            cy.wait(2000)
            cy.get('label').eq(0).click()
            cy.get('button[data-button-use="primary"]').click()
            cy.wait(2000)
            cy.get('button[data-button-use="primary"]').click()
        })

        cy.wait(5000) // wait for redirect
        cy.get('button[type="submit"]').eq(0).click()
        cy.get('[data-attr=success-toast]').contains('Configuration saved').should('exist')
    })
})
