describe('Surveys', () => {
    let name

    beforeEach(() => {
        name = 'survey-' + Math.floor(Math.random() * 10000000)
        cy.clickNavMenu('surveys')
    })

    it('shows get started state on first load', () => {
        // load an empty page
        cy.get('h1').should('contain', 'Surveys')
        cy.title().should('equal', 'Surveys • PostHog')

        cy.contains('Create your first survey').should('exist')

        // go to create a new survey
        cy.get('[data-attr="create-survey"]').click()
        cy.get('[data-attr="new-blank-survey"]').click()

        cy.get('[data-attr="survey-name"]').type(name)

        // save
        cy.get('[data-attr="save-survey"]').click()
        cy.get('[data-attr=success-toast]').contains('created').should('exist')

        // back to surveys
        cy.clickNavMenu('surveys')
        cy.get('[data-attr=surveys-table]').should('contain', name)
        cy.contains('Create your first survey').should('not.exist')

        // back into survey
        cy.get(`[data-row-key="${name}"]`).contains(name).click()

        // delete survey
        cy.get('[data-attr="more-button"]').click()
        cy.get('.Popover__content').contains('Delete').click()
        cy.clickNavMenu('surveys')

        cy.get('tbody').should('not.exist')
    })

    it('creates a new survey', () => {
        // load an empty page
        cy.get('h1').should('contain', 'Surveys')
        cy.title().should('equal', 'Surveys • PostHog')

        // click via top right button
        cy.get('[data-attr="new-survey"]').click()
        cy.get('[data-attr="new-blank-survey"]').click()

        // select "add filter" and "property"
        cy.get('[data-attr="survey-name"]').type(name)
        cy.get('[data-attr="survey-question-type-0"]').click()
        cy.contains('Rating').click()

        // should pre-fill the question based on template
        cy.get('[id="scenes.surveys.surveyLogic.new.survey.questions.0.question"]').should(
            'include.value',
            'How likely are you to recommend'
        )

        cy.get('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]')
            .invoke('html')
            .should('include', '0 - 10')

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
        cy.get('.LemonCollapsePanel').contains('Targeting').click()
        cy.contains('All users').click()
        cy.get('.Popover__content').contains('Users who match').click()
        cy.contains('Add user targeting').click()

        // select the first property
        cy.get('[data-attr="property-select-toggle-0"]').click()
        cy.get('[data-attr="prop-filter-person_properties-0"]').click()
        cy.get('[data-attr=prop-val] .ant-select-selector').click({ force: true })
        cy.get('[data-attr=prop-val-0]').click({ force: true })

        cy.get('[data-attr="rollout-percentage"]').type('100')

        // save
        cy.get('[data-attr="save-survey"]').click()
        cy.get('[data-attr=success-toast]').contains('created').should('exist')

        // check preview release conditions
        cy.contains('Release conditions summary').should('exist')
        cy.get('.FeatureConditionCard').should('exist').should('contain.text', 'is_demo equals true')
        cy.get('.FeatureConditionCard').should('contain.text', 'Rolled out to 100% of users in this set.')

        // launch survey
        cy.get('[data-attr="launch-survey"]').click()

        // refresh, see survey show up on page
        cy.reload()

        cy.contains('Unique users shown').should('exist')

        // stop survey
        cy.contains('Stop').click()

        // back to surveys
        cy.clickNavMenu('surveys')
        cy.get('[data-attr=surveys-table]').should('contain', name)

        // back into survey
        cy.get(`[data-row-key="${name}"]`).contains(name).click()

        // edit
        cy.get('[data-attr="more-button"]').click()
        cy.get('.Popover__content').contains('Edit').click()

        // remove user targeting properties
        cy.get('.LemonCollapsePanel').contains('Targeting').click()
        cy.contains('Remove all user properties').click()

        // save
        cy.get('[data-attr="save-survey"]').click()

        // check preview release conditions
        cy.get('.LemonTabs').contains('Overview').click()
        cy.contains('Release conditions summary').should('exist')
        cy.get('.FeatureConditionCard').should('not.exist')

        // delete survey
        cy.get('[data-attr="more-button"]').click()
        cy.get('.Popover__content').contains('Delete').click()
        cy.clickNavMenu('surveys')
        cy.get('tbody').should('not.exist')
    })

    it('Delete survey', () => {
        cy.get('h1').should('contain', 'Surveys')
        cy.get('[data-attr=new-survey]').click()
        cy.get('[data-attr=new-blank-survey]').click()
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

    it('creates a new multiple choice survey with an open-ended choice', () => {
        cy.get('h1').should('contain', 'Surveys')
        cy.get('[data-attr=new-survey]').click()
        cy.get('[data-attr=new-blank-survey]').click()

        // add a multiple choice question with an open-ended question
        cy.get('[data-attr=survey-name]').focus().type(name).should('have.value', name)
        cy.get('[data-attr="survey-question-type-0"]').click()
        cy.contains('Multiple choice select').click()
        cy.get('button').contains('Add open-ended choice').click()

        // check default open-ended choice form input and appearance after
        // open-ended choice was added
        cy.get('.LemonInput__input[value="Other"]')
        cy.get('.choice-option').eq(3).contains('Other:')
        cy.get('.choice-option').eq(3).find('input[type="text"]').should('have.value', '')

        // typing in open-ended question's appearance automatically checks the
        // checkbox
        cy.get('.choice-option').eq(3).find('input[type="checkbox"]').should('not.be.checked')
        cy.get('.choice-option').eq(3).find('input[type="text"]').type('Outreach')
        cy.get('.choice-option').eq(3).find('input[type="checkbox"]').should('be.checked')

        // clicking on open-ended question's appearance label unchecks or checks
        // the checkbox
        cy.get('.choice-option').eq(3).click()
        cy.get('.choice-option').eq(3).find('input[type="checkbox"]').should('not.be.checked')
        cy.get('.choice-option').eq(3).click()
        cy.get('.choice-option').eq(3).find('input[type="checkbox"]').should('be.checked')

        // removing text in open-ended question's appearance automatically
        // unchecks the checkbox
        cy.get('.choice-option').eq(3).find('input[type="text"]').clear()

        // open-ended question label doesn't change even if appearance input
        // changes
        cy.get('.LemonInput__input[value="Other"]')

        // change open-ended choice after the label was added
        cy.contains('Choices').parent().find('input[type="text"]').eq(3).clear()
        cy.contains('Choices').parent().find('input[type="text"]').eq(3).type('First Choice')
        cy.get('.choice-option').eq(3).contains('First Choice:')

        // attempt to create and save survey
        cy.get('[data-attr=save-survey]').first().click()

        // after save there should be a launch button
        cy.get('button[data-attr="launch-survey"]').should('have.text', 'Launch')

        cy.clickNavMenu('surveys')
        cy.get('[data-attr=surveys-table]').should('contain', name)
        cy.get(`[data-row-key="${name}"]`).contains(name).click()
    })
})
