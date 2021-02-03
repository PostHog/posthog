describe('Setup', () => {
    it('Setup loaded', () => {
        cy.get('.navigation-inner').scrollTo(0, 1000)
        cy.get('[data-attr=menu-item-projectSettings]').click()
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
        cy.get('.navigation-inner').scrollTo(0, 1000) // Go to the bottom of the navigation bar
        cy.get('[data-attr=menu-item-projectSettings]').click()
        cy.get('[data-attr=app-url-suggestion]').first().click()
        cy.get('[data-attr=app-url-item]').contains(/\hogflix/g)

        cy.title().should('equal', 'Project Settings • PostHog')
    })
})
