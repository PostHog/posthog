describe('Notebooks', () => {
    beforeEach(() => {
        cy.fixture('api/session-recordings/recordings.json').then((recordings) => {
            cy.intercept('GET', /api\/projects\/\d+\/session_recordings\/?\?.*/, { body: recordings }).as(
                'loadSessionRecordingsList'
            )
        })
        cy.fixture('api/session-recordings/recording.json').then((recording) => {
            cy.intercept('GET', /api\/projects\/\d+\/session_recordings\/.*\?.*/, { body: recording }).as(
                'loadSessionRecording'
            )
        })

        cy.clickNavMenu('dashboards')
        cy.location('pathname').should('include', '/dashboard')
    })

    it('Notebooks are enabled', () => {
        cy.get('h1').should('contain', 'Dashboards & Notebooks')
        cy.get('li').contains('Notebooks').should('exist').click()
    })
})
