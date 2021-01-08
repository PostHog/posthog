describe('Setup', () => {
    it('Setup loaded', () => {
        cy.get('[data-attr=menu-item-project]').click()
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
        cy.get('[data-attr=menu-item-project]').click()
        cy.get('[data-attr=app-url-suggestion]').click()
        cy.get('[data-attr=app-url-item]').contains(/\/insights|\/demo/g)

        cy.title().should('equal', 'Project Settings • PostHog')
    })

    it('Delete and create only project', () => {
        cy.get('[data-attr=menu-item-settings]').click()
        cy.get('[data-attr=menu-item-project-settings]').click()
        cy.get('h1').should('contain', 'Project Settings')
        cy.get('[data-attr=delete-project-button]').click()
        cy.get('[data-attr=delete-project-ok]').click()
        cy.get('.ant-modal-title').should('contain.text', 'Creating a Project')
        cy.get('[data-attr=create-project-ok]').click()
        cy.get('.ant-alert').should('contain.text', 'Your project needs a name!')
        cy.get('input').type('Project X').should('have.value', 'Project X')
        cy.get('[data-attr=create-project-ok]').click()
        cy.get('[data-attr=user-project-dropdown]').should('contain.text', 'Project X')
    })
})
