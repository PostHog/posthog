// import { urls } from 'scenes/urls'
// import { randomString } from '../support/random'
// import { insight, savedInsights, dashboards, dashboard, duplicateDashboardFromMenu } from '../productAnalytics'

describe('Notebooks', () => {
    beforeEach(() => {
        cy.intercept('GET', /api\/projects\/\d+\/insights\/\?.*/).as('loadInsightList')
        cy.intercept('PATCH', /api\/projects\/\d+\/insights\/\d+\/.*/).as('patchInsight')

        cy.fixture('api/session_recordings.json').then((recordings) => {
            cy.intercept('GET', /api\/projects\/\d+\/session_recordings\/?\?.*/, { body: recordings }).as(
                'loadSessionRecordingsList'
            )
        })
        cy.fixture('api/session_recording.json').then((recording) => {
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
        // cy.get('li').should('contain', 'Notebooks').click()
    })

    // it('Notebooks loaded', () => {
    //     cy.get('h1').should('contain', 'Dashboards')
    //     // Breadcrumbs work
    //     cy.get('[data-attr=breadcrumb-0]').should('contain', 'Hogflix')
    //     cy.get('[data-attr=breadcrumb-1]').should('contain', 'Hogflix Demo App')
    //     cy.get('[data-attr=breadcrumb-2]').should('have.text', 'Dashboards')
    // })
})
