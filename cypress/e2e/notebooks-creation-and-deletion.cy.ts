import { randomString } from '../support/random'

function visitNotebooksList(): void {
    cy.clickNavMenu('notebooks')
    cy.location('pathname').should('include', '/notebooks')
    cy.get('h1').should('contain', 'Notebooks')
    cy.get('li').contains('Notebooks').should('exist').click()
}

function createNotebookAndFindInList(notebookTitle: string): void {
    cy.get('[data-attr="new-notebook"]').click()
    cy.get('.NotebookEditor').type(notebookTitle)

    visitNotebooksList()
    cy.get('[data-attr="notebooks-search"]').type(notebookTitle)
}

describe('Notebooks', () => {
    beforeEach(() => {
        visitNotebooksList()
    })

    it('can create and name a notebook', () => {
        const notebookTitle = randomString('My new notebook')

        createNotebookAndFindInList(notebookTitle)
        cy.get('[data-attr="notebooks-table"] tbody tr').should('have.length', 1)
    })

    it('can delete a notebook', () => {
        const notebookTitle = randomString('My notebook to delete')

        createNotebookAndFindInList(notebookTitle)

        cy.contains('[data-attr="notebooks-table"] tr', notebookTitle).within(() => {
            cy.get('[aria-label="more"]').click()
        })
        cy.contains('.LemonButton', 'Delete').click()

        // and the table updates
        cy.contains('[data-attr="notebooks-table"] tr', notebookTitle).should('not.exist')
    })
})
