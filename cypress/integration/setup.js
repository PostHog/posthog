describe('Setup', () => {
    it('Setup loaded', () => {
        cy.get('[data-attr=menu-item-settings]', { timeout: 7000 }).click()
        cy.get('[data-attr=layout-content]', { timeout: 7000 }).should('exist')
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
        cy.get('[data-attr=menu-item-settings]').click()
        cy.get('[data-attr=app-url-suggestion]').click()
        cy.get('[data-attr=app-url-item]').should('contain', '/demo')
    })
})
