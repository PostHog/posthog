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
        //get 2nd element matching the selector
        cy.get('[data-attr="save-survey"]').eq(0).click()
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
        // Handle the confirmation dialog
        cy.get('.LemonModal__footer').should('be.visible')
        cy.contains('Delete this survey?').should('be.visible')
        cy.get('.LemonModal__footer').contains('button', 'Delete').click()

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
        cy.get('[class="survey-form"]')
            .should('contain', 'How likely are you to recommend us to a friend?')
            .should('contain', 'Unlikely')
            .should('contain', 'Very likely')
        cy.get('[class="survey-form"]').find('.ratings-number').should('have.length', 5)

        // add targeting filters
        cy.get('.LemonCollapsePanel').contains('Display conditions').click()
        cy.contains('All users').click()
        cy.get('.Popover__content').contains('Users who match').click()
        cy.contains('Add user targeting').click()

        // select the first property
        cy.get('[data-attr="property-select-toggle-0"]').click()
        cy.get('[data-attr="prop-filter-person_properties-0"]').click()
        cy.get('[data-attr=prop-val]').click({ force: true })
        cy.get('[data-attr=prop-val-0]').click({ force: true })

        cy.get('[data-attr="rollout-percentage"]').type('100')

        // save
        cy.get('[data-attr="save-survey"]').eq(0).click()

        cy.get('[data-attr=success-toast]').contains('created').should('exist')

        // check preview release conditions
        cy.contains('Display conditions summary').should('exist')
        cy.get('.FeatureConditionCard').should('exist').should('contain.text', 'is_demo equals true')
        cy.get('.FeatureConditionCard').should('contain.text', 'Rolled out to 100% of users in this set.')

        // launch survey
        cy.get('[data-attr="launch-survey"]').click()
        // Handle the confirmation dialog
        cy.get('.LemonModal__layout').should('be.visible')
        cy.contains('Launch this survey?').should('be.visible')
        cy.get('.LemonModal__footer').contains('button', 'Launch').click()

        // refresh, see survey show up on page
        cy.reload()

        cy.contains('Unique users shown').should('exist')

        // Update the stop survey part
        cy.contains('Stop').click()
        // Handle the confirmation dialog
        cy.get('.LemonModal__layout').should('be.visible')
        cy.contains('Stop this survey?').should('be.visible')
        cy.get('.LemonModal__footer').contains('button', 'Stop').click()

        // back to surveys
        cy.clickNavMenu('surveys')
        cy.get('[data-attr=surveys-table]').should('contain', name)

        // back into survey
        cy.get(`[data-row-key="${name}"]`).contains(name).click()

        // edit
        cy.get('[data-attr="more-button"]').click()
        cy.get('.Popover__content').contains('Edit').click()

        // remove user targeting properties
        cy.get('.LemonCollapsePanel').contains('Display conditions').click()
        cy.contains('Remove all user properties').click()

        // save
        cy.get('[data-attr="save-survey"]').eq(0).click()

        // check preview release conditions
        cy.get('.LemonTabs').contains('Overview').click()
        cy.contains('Display conditions summary').should('exist')
        cy.get('.FeatureConditionCard').should('not.exist')

        // delete survey
        cy.get('[data-attr="more-button"]').click()
        cy.get('.Popover__content').contains('Delete').click()
        // handle confirmation dialog
        cy.get('.LemonModal__layout').should('be.visible')
        cy.contains('Delete this survey?').should('be.visible')
        cy.get('.LemonModal__footer').contains('button', 'Delete').click()
        cy.clickNavMenu('surveys')
        cy.get('tbody').should('not.exist')
    })

    it('deletes a survey', () => {
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
        // Handle the confirmation dialog
        cy.get('.LemonModal__layout').should('be.visible')
        cy.contains('Delete this survey?').should('be.visible')
        cy.get('.LemonModal__footer').contains('button', 'Delete').click()
        cy.get('.Toastify__toast-body').contains('Survey deleted').should('be.visible')
    })

    it('duplicates a survey', () => {
        // create survey
        cy.get('[data-attr=new-survey]').click()
        cy.get('[data-attr=new-blank-survey]').click()
        cy.get('[data-attr=survey-name]').focus().type(name).should('have.value', name)

        // Add user targetting criteria
        cy.get('.LemonCollapsePanel').contains('Display conditions').click()
        cy.contains('All users').click()
        cy.get('.Popover__content').contains('Users who match').click()
        cy.contains('Add user targeting').click()
        cy.get('[data-attr="property-select-toggle-0"]').click()
        cy.get('[data-attr="prop-filter-person_properties-0"]').click()
        cy.get('[data-attr=prop-val]').click({ force: true })
        cy.get('[data-attr=prop-val-0]').click({ force: true })
        cy.get('[data-attr="rollout-percentage"]').type('100')

        cy.get('[data-attr=save-survey]').first().click()

        // Launch the survey first, the duplicated one should be in draft
        cy.get('[data-attr="launch-survey"]').click()
        // Handle the confirmation dialog
        cy.get('.LemonModal__footer').should('be.visible')
        cy.contains('Launch this survey?').should('be.visible')
        cy.get('.LemonModal__footer').contains('button', 'Launch').click()

        // try to duplicate survey
        cy.get('[data-attr=more-button]').click()
        cy.get('[data-attr=duplicate-survey]').click()

        // if the survey is duplicated, try to view it & verify a copy is created
        cy.get('[data-attr=success-toast]').contains('duplicated').should('exist').siblings('button').click()
        cy.get('[data-attr=top-bar-name]').contains(`${name} (copy)`).should('exist')

        // check if it launched in a draft state
        cy.get('button[data-attr="launch-survey"]').should('have.text', 'Launch')

        // check if targetting criteria is copied
        cy.contains('Display conditions summary').should('exist')
        cy.get('.FeatureConditionCard').should('exist').should('contain.text', 'is_demo equals true')
        cy.get('.FeatureConditionCard').should('contain.text', 'Rolled out to 100% of users in this set.')

        // delete the duplicated survey
        cy.get('[data-attr=more-button]').click()
        cy.get('[data-attr=delete-survey]').click()
        cy.get('.LemonModal__footer').should('be.visible')
        cy.contains('Delete this survey?').should('be.visible')
        cy.get('.LemonModal__footer').contains('button', 'Delete').click()

        // Archive the original survey
        cy.clickNavMenu('surveys')
        cy.get('[data-attr=surveys-table]').find(`[data-row-key="${name}"]`).find('a').click()
        cy.get('[data-attr=stop-survey]').click()
        cy.get('.LemonModal__footer').should('be.visible')
        cy.contains('Stop this survey?').should('be.visible')
        cy.get('.LemonModal__footer').contains('button', 'Stop').click()
        cy.get('[data-attr=more-button]').click()
        cy.get('[data-attr=archive-survey]').click()
        cy.get('.LemonModal__footer').should('be.visible')
        cy.contains('Archive this survey?').should('be.visible')
        cy.get('.LemonModal__footer').contains('button', 'Archive').click()

        // check if the duplicated survey is created with draft state
        cy.get('[data-attr=more-button]').click()
        cy.get('[data-attr=duplicate-survey]').click()
        cy.clickNavMenu('surveys')
        cy.get('[data-attr=surveys-table]')
            .find(`[data-row-key="${name} (copy)"]`)
            .find('[data-attr=status]')
            .contains('DRAFT')
            .should('exist')
    })

    it('can set responses limit', () => {
        cy.get('h1').should('contain', 'Surveys')
        cy.get('[data-attr=new-survey]').click()
        cy.get('[data-attr=new-blank-survey]').click()

        cy.get('[data-attr=survey-name]').focus().type(name)

        // Set responses limit
        cy.get('.LemonCollapsePanel').contains('Completion conditions').click()
        cy.get('[data-attr=survey-responses-limit-input]').focus().type('228').click()

        // Save the survey
        cy.get('[data-attr=save-survey]').first().click()
        cy.get('button[data-attr="launch-survey"]').should('have.text', 'Launch')

        cy.reload()
        cy.contains('The survey will be stopped once 228 responses are received.').should('be.visible')
    })

    it('creates a new survey with branching logic', () => {
        cy.window().then((win) => {
            win.POSTHOG_APP_CONTEXT.current_user.organization.available_product_features = [
                {
                    key: 'surveys_multiple_questions',
                    name: 'Multiple questions',
                    description: 'Ask up to 10 questions in a single survey.',
                    unit: null,
                    limit: null,
                    note: null,
                },
            ]

            cy.get('h1').should('contain', 'Surveys')
            cy.title().should('equal', 'Surveys • PostHog')

            cy.get('[data-attr="new-survey"]').click()
            cy.get('[data-attr="new-blank-survey"]').click()
            cy.get('[data-attr="survey-name"]').type(name)

            // Prepare questions
            cy.get('[data-attr=survey-question-label-0]')
                .focus()
                .clear()
                .type('How happy are you?', { delay: 0 })
                .should('have.value', 'How happy are you?')
            cy.get('[data-attr=survey-question-type-0]').click()
            cy.get('[data-attr=survey-question-type-0-rating]').click()
            cy.get('[data-attr="add-question"]').click()

            cy.get('[data-attr=survey-question-label-1]')
                .focus()
                .clear()
                .type('Sorry to hear that. Please tell us more!', { delay: 0 })
                .should('have.value', 'Sorry to hear that. Please tell us more!')
            cy.get('[data-attr="add-question"]').click()

            cy.get('[data-attr=survey-question-label-2]')
                .focus()
                .clear()
                .type('Seems you are not completely happy. Please tell us more!', { delay: 0 })
                .should('have.value', 'Seems you are not completely happy. Please tell us more!')
            cy.get('[data-attr="add-question"]').click()

            cy.get('[data-attr=survey-question-label-3]')
                .focus()
                .clear()
                .type('Glad to hear that! Please tell us more', { delay: 0 })
                .should('have.value', 'Glad to hear that! Please tell us more')
            cy.get('[data-attr="add-question"]').click()

            cy.get('[data-attr=survey-question-label-4]')
                .focus()
                .clear()
                .type('Would you like to leave us a review?', { delay: 0 })
                .should('have.value', 'Would you like to leave us a review?')
            cy.get('[data-attr=survey-question-type-4]').click()
            cy.get('[data-attr=survey-question-type-4-single_choice]').click()
            cy.get('[data-attr="add-question"]').click()

            cy.get('[data-attr=survey-question-label-5]')
                .focus()
                .clear()
                .type('Please write your review here', { delay: 0 })
                .should('have.value', 'Please write your review here')

            // Set branching
            // Question 1 - How happy are you?
            cy.get('[data-attr=survey-question-panel-0]').click()
            // Default branching is always "Next question"
            cy.get('button[data-attr="survey-question-0-branching-select"]').find('span').contains('Next question')
            cy.get('[data-attr=survey-question-0-branching-select]').click()
            cy.get('.Popover__box button').contains('span', 'Specific question based on answer').click()
            cy.get('button[data-attr="survey-question-0-branching-select"]')
                .find('span')
                .contains('Specific question based on answer')

            cy.get('[data-attr=survey-question-0-branching-response_based-select-0]').click()
            cy.get('.Popover__box button').contains('span', '2.').click()
            cy.get('button[data-attr="survey-question-0-branching-response_based-select-0"]')
                .find('span')
                .contains('2.')

            cy.get('[data-attr=survey-question-0-branching-response_based-select-1]').click()
            cy.get('.Popover__box button').contains('span', '3.').click()
            cy.get('button[data-attr="survey-question-0-branching-response_based-select-1"]')
                .find('span')
                .contains('3.')

            cy.get('[data-attr=survey-question-0-branching-response_based-select-2]').click()
            cy.get('.Popover__box button').contains('span', '4.').click()
            cy.get('button[data-attr="survey-question-0-branching-response_based-select-2"]')
                .find('span')
                .contains('4.')

            // Question 2 - Sorry to hear that...
            cy.get('[data-attr=survey-question-panel-1]').click()
            cy.get('[data-attr=survey-question-1-branching-select]').click()
            cy.get('.Popover__box button').contains('span', 'Confirmation message').click()
            cy.get('button[data-attr="survey-question-1-branching-select"]')
                .find('span')
                .contains('Confirmation message')

            // Question 3 - Seems you are not completely happy...
            cy.get('[data-attr=survey-question-panel-2]').click()
            cy.get('[data-attr=survey-question-2-branching-select]').click()
            cy.get('.Popover__box button').contains('span', 'Confirmation message').click()
            cy.get('button[data-attr="survey-question-2-branching-select"]')
                .find('span')
                .contains('Confirmation message')

            // Question 4 - Glad to hear that...
            cy.get('[data-attr=survey-question-panel-3]').click()
            cy.get('[data-attr=survey-question-3-branching-select]').click()
            // "Would you like to leave us a review?"
            cy.get('.Popover__box button').contains('span', '5.').click()
            cy.get('button[data-attr="survey-question-3-branching-select"]').find('span').contains('5.')

            // Question 5 - Would you like to leave us a review?
            cy.get('[data-attr=survey-question-panel-4]').click()
            cy.get('[data-attr=survey-question-4-branching-select]').click()
            cy.get('.Popover__box button').contains('span', 'Specific question based on answer').click()
            cy.get('button[data-attr="survey-question-4-branching-select"]')
                .find('span')
                .contains('Specific question based on answer')

            cy.get('[data-attr=survey-question-4-branching-response_based-select-0]').click()
            cy.get('.Popover__box button').contains('span', 'Next question').click()
            cy.get('button[data-attr="survey-question-4-branching-response_based-select-0"]')
                .find('span')
                .contains('Next question')

            cy.get('[data-attr=survey-question-4-branching-response_based-select-1]').click()
            cy.get('.Popover__box button').contains('span', 'Confirmation message').click()
            cy.get('button[data-attr="survey-question-4-branching-response_based-select-1"]')
                .find('span')
                .contains('Confirmation message')

            // Question 6 - Please write your review here
            cy.get('[data-attr=survey-question-panel-5]').click()
            cy.get('button[data-attr="survey-question-5-branching-select"]')
                .find('span')
                .contains('Confirmation message')

            // Save
            cy.get('[data-attr="save-survey"]').eq(0).click()
            cy.get('[data-attr=success-toast]').contains('created').should('exist')
        })
    })
})
