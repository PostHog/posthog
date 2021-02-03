describe('Setup', () => {
    it('Setup loaded', () => {
        cy.visit('/project/settings')
        cy.get('[data-attr=menu-item-projectSettings]').should('exist') // TODO: Solve navigation bar scroll issue and get to page from menu
        cy.get('[data-attr=layout-content]').should('exist')
    })

    it('See suggestion and save', () => {
        cy.getCookie('csrftoken').then((csrftoken) => {
            cy.request({
                url: '/api/user/',
                body: { team: { app_urls: [] } },
                method: 'PATCH',
                headers: {
                    'X-CSRFToken': csrftoken.value,
                },
            })
        })
        cy.reload(true)
        cy.visit('/project/settings')
        cy.get('[data-attr=app-url-suggestion]').first().click()
        cy.get('[data-attr=app-url-item]').contains(/\hogflix/g)

        cy.title().should('equal', 'Project Settings • PostHog')
    })
})
