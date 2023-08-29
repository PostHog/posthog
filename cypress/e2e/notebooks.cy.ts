import { urls } from 'scenes/urls'

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
        cy.fixture('api/notebooks/notebooks.json').then((notebook) => {
            cy.intercept('GET', /api\/projects\/\d+\/notebooks\//, { body: notebook }).as('loadNotebooksList')
        })
        cy.fixture('api/notebooks/notebook.json').then((notebook) => {
            cy.intercept('GET', /api\/projects\/\d+\/notebooks\/.*\//, { body: notebook }).as('loadNotebook')
        })

        cy.clickNavMenu('dashboards')
        cy.location('pathname').should('include', '/dashboard')
    })

    it('Notebooks are enabled', () => {
        cy.get('h1').should('contain', 'Dashboards & Notebooks')
        cy.get('li').contains('Notebooks').should('exist').click()
    })

    it('Notebooks can render rich nodes', () => {
        cy.visit(urls.notebook('h11RoiwV'))
        cy.get('.ph-recording.NotebookNode').should('exist')
    })

    it('Insertion suggestions can be dismissed', () => {
        cy.visit(urls.notebookEdit('h11RoiwV'))
        cy.get('.NotebookEditor').type('{enter}')

        cy.get('.NotebookRecordingTimestamp--preview').should('exist')

        cy.get('.NotebookEditor').type('{esc}')
        cy.get('.NotebookFloatingButton .LemonButton').should('exist')
    })

    it('Can comment on a recording', () => {
        cy.visit(urls.replay())
        cy.get('[data-attr="notebooks-replay-comment-button"]').click()

        cy.get('.LemonButton').contains('Comment in a new notebook').click()

        cy.get('.Notebook.Notebook--editable').should('be.visible')
        cy.get('.ph-recording.NotebookNode').should('be.visible')
        cy.get('.NotebookRecordingTimestamp').should('contain.text', '0:00')
    })
})
