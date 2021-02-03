Cypress.Commands.add('interceptLazy', (pattern, handler) => {
    return cy.intercept(pattern, (req) => {
        req.reply(handler())
    })
})
