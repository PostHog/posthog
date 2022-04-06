const patternHandler = {}

Cypress.Commands.add('interceptLazy', (pattern, handler) => {
    patternHandler[pattern] = handler
    return cy.intercept(pattern, (req) => {
        req.reply(patternHandler[pattern]())
    })
})

Cypress.Commands.add('login', () => {
    // This function isn't used for every test anymore
    cy.get('[data-attr=login-email]').type('test@posthog.com').should('have.value', 'test@posthog.com').blur()

    cy.get('[data-attr=password]', { timeout: 5000 }).should('be.visible') // Wait for login precheck (note blur above)
    cy.get('[data-attr=password]').type('12345678').should('have.value', '12345678')

    cy.get('[type=submit]').click()

    cy.location('pathname').should('not.eq', '/login') // Wait until login request fully completes
})

Cypress.Commands.add('overrideInterceptLazy', (pattern, handler) => {
    patternHandler[pattern] = handler
})

Cypress.Commands.add('map', { prevSubject: true }, (subject, method) => {
    return method(subject)
})

Cypress.Commands.add('clickNavMenu', (name) => {
    cy.get(`[data-attr="menu-item-${name}"]`).click().should('have.class', 'LemonButton--highlighted')
})
