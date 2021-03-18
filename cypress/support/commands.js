import 'cypress-plugin-snapshots/commands'

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
