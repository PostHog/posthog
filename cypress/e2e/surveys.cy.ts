describe('Surveys', () => {
    let name

    beforeEach(() => {
        name = 'survey-' + Math.floor(Math.random() * 10000000)
        cy.clickNavMenu('surveys')
    })

    it('creates a new survey', () => {
        // load an empty page
        cy.get('h1').should('contain', 'Surveys')
        cy.title().should('equal', 'Surveys • PostHog')

        cy.get('h2').should('contain', 'Create your first survey')

        // go to create a new survey
        cy.get('[data-attr="create-survey"]').click()

        // click via top right button
        // cy.get('[data-attr="new-survey"]').click()

        // select "add filter" and "property"
        cy.get('[data-attr="survey-name"]').type('Test Survey')
        cy.get('[data-attr="survey-question-type-0"]').click()
        cy.contains('Rating').click()

        // should pre-fill the question based on template
        cy.get('[id="scenes.surveys.surveyLogic.new.survey.questions.0.question"]').should(
            'include.value',
            'How likely are you to recommend'
        )

        cy.get('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]')
            .invoke('html')
            .should('include', '1 - 10')

        cy.get('[id="scenes.surveys.surveyLogic.new.survey.questions.0.upperBoundLabel"]').should(
            'have.value',
            'Very likely'
        )

        // change the scale
        cy.get('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]').click()
        cy.contains('1 - 5').click()

        cy.get('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]')
            .invoke('html')
            .should('include', '1 - 5')

        // make sure the preview is updated
        cy.get('[data-attr="survey-preview"]')
            .find('form')
            .should('contain', 'How likely are you to recommend us to a friend?')
            .should('contain', 'Unlikely')
            .should('contain', 'Very likely')
        cy.get('[data-attr="survey-preview"]').find('form').find('.ratings-number').should('have.length', 5)

        // add targeting filters

        // add linked feature flag

        // save
        cy.get('[data-attr="save-survey"]').click()
        cy.get('[data-attr=success-toast]').contains('Survey created').should('exist')

        // launch survey

        // refresh, see survey show up on page

        // back to surveys
        cy.clickNavMenu('surveys')
        cy.get('[data-attr=surveys-table]').should('contain', 'Test Survey')
        cy.get('h2').should('not.have.text', 'Create your first survey')

        it('handles user targeting properties', () => {
            // remove user targeting properties
        })

        // back into survey
        cy.get(`[data-row-key="Test Survey"]`).contains('Test Survey').click()

        // delete survey
        cy.get('[data-attr="more-button"]').click()
        cy.get('.Popover__content').contains('Delete').click()
        cy.clickNavMenu('surveys')
        cy.get('tbody').should('not.have.text', 'Test Survey')
    })

    it('Delete survey', () => {
        cy.get('h1').should('contain', 'Surveys')
        cy.get('[data-attr=new-survey]').click()
        cy.get('[data-attr=survey-name]').focus().type(name).should('have.value', name)
        cy.get('[data-attr=save-survey]').first().click()

        // after save there should be a launch button
        cy.get('button[data-attr="launch-survey"]').should('have.text', 'Launch')

        cy.clickNavMenu('surveys')
        cy.get('[data-attr=surveys-table]').should('contain', name)
        cy.get(`[data-row-key=${name}]`).contains(name).click()
        cy.get('[data-attr=more-button]').click()
        cy.get('[data-attr=delete-survey]').click()
        cy.get('.Toastify__toast-body').contains('Survey deleted').should('be.visible')
    })
})
