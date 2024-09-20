Cypress.Commands.add('login', () => {
    // This function isn't used for every test anymore
    cy.get('[data-attr=login-email]').type('test@posthog.com').should('have.value', 'test@posthog.com').blur()

    cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
    cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')

    cy.get('[type=submit]').click()

    cy.location('pathname').should('not.eq', '/login') // Wait until login request fully completes
})

Cypress.Commands.add('clickNavMenu', (name) => {
    cy.get(`[data-attr="menu-item-${name}"]`).click()
})

Cypress.Commands.add('useSubscriptionStatus', (condition) => {
    if (condition === 'unsubscribed') {
        cy.intercept('/api/billing/', { fixture: 'api/billing/billing-unsubscribed.json' })
        cy.reload()
    } else if (condition === 'subscribed') {
        cy.intercept('/api/billing/', { fixture: 'api/billing/billing-subscribed-all.json' })
        cy.reload()
    }
})
