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
            // this means saving doesn't work but so what?
            cy.intercept('PATCH', /api\/projects\/\d+\/notebooks\/.*\//, (req, res) => {
                res.reply(req.body)
            }).as('patchNotebook')
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
        cy.visit(urls.notebook('h11RoiwV'))
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

    describe('text types', () => {
        beforeEach(() => {
            cy.get('li').contains('Notebooks').should('exist').click()
            cy.get('[data-attr="new-notebook"]').click()
            // we don't actually get a new notebook because the API is mocked
            // so, "exit" the timestamp block we start in
            cy.get('.NotebookEditor').type('{esc}{enter}{enter}')
        })

        it('Can add a number list', () => {
            cy.get('.NotebookEditor').type('1. the first')
            cy.get('.NotebookEditor').type('{enter}')
            // no need to type the number now. it should be inserted automatically
            cy.get('.NotebookEditor').type('the second')
            cy.get('.NotebookEditor').type('{enter}')
            cy.get('ol').should('contain.text', 'the first')
            cy.get('ol').should('contain.text', 'the second')
            // the numbered list auto inserts the next list item
            cy.get('.NotebookEditor ol li').should('have.length', 3)
        })

        it('Can add bold', () => {
            cy.get('.NotebookEditor').type('**bold**')
            cy.get('.NotebookEditor p').last().should('contain.html', '<strong>bold</strong>')
        })

        it('Can add bullet list', () => {
            cy.get('.NotebookEditor').type('* the first{enter}the second{enter}')
            cy.get('ul').should('contain.text', 'the first')
            cy.get('ul').should('contain.text', 'the second')
            // the list auto inserts the next list item
            cy.get('.NotebookEditor ul li').should('have.length', 3)
        })
    })
})
