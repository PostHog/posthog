const patternHandler = {}

Cypress.Commands.add('interceptLazy', (pattern, handler) => {
    patternHandler[pattern] = handler
    return cy.intercept(pattern, (req) => {
        req.reply(patternHandler[pattern]())
    })
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
