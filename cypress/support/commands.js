Cypress.Commands.add('interceptLazy', (pattern, handler) => {
    return cy.intercept(pattern, (req) => {
        req.reply(handler())
    })
})

Cypress.Commands.add('map', { prevSubject: true }, (subject, method) => {
    return method(subject)
})
