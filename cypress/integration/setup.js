describe('Setup', () => {
    it('Setup loaded', () => {
        cy.get('[data-attr=menu-item-setup]').click()
        cy.get('[data-attr=layout-content]').should('exist')
    })

    it('See suggestion and save', () => {
        cy.getCookie('csrftoken')
        .then((csrftoken) => {
            cy.request({
                url: '/api/user/',
                body: {team: {app_urls: []}},
                method: 'PATCH',
                headers: {
                'X-CSRFToken': csrftoken.value,
            }})
        })
        cy.reload(true)
        cy.get('[data-attr=menu-item-setup]').click()
        cy.get('[data-attr=app-url-suggestion]').click()
        cy.wait(500) // not ideal but toast has a delay render
        cy.get('.Toastify__toast').should('contain', 'URLs saved')
    })
})
