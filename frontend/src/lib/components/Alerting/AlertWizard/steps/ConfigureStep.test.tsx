import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AlertWizardLogicProps, alertWizardLogic } from '../alertWizardLogic'
import { ConfigureStep } from './ConfigureStep'

const PROPS: AlertWizardLogicProps = {
    logicKey: 'configure-step-test',
    subTemplateIds: ['error-tracking-issue-created'],
    triggers: [{ key: 'error-tracking-issue-created', name: 'Issue created', description: 'A new issue' }],
    destinations: [
        {
            key: 'slack',
            name: 'Slack',
            description: 'Send a message to a channel',
            icon: '/static/services/slack.png',
            templateId: 'template-slack',
        },
        {
            key: 'github',
            name: 'GitHub',
            description: 'Create an issue in a repository',
            icon: '/static/services/github.png',
            templateId: 'template-github',
        },
    ],
    disableUrlSync: true,
}

const TEMPLATE_FIELD_LABELS: Record<string, string> = {
    'template-slack': 'Slack channel',
    'template-github': 'GitHub repository',
}

function renderConfigureStep(): ReturnType<typeof alertWizardLogic.build> {
    const logic = alertWizardLogic(PROPS)
    logic.mount()
    render(
        <Provider>
            <BindLogic logic={alertWizardLogic} props={PROPS}>
                <ConfigureStep />
            </BindLogic>
        </Provider>
    )
    return logic
}

const settle = async (): Promise<void> => {
    await act(() => new Promise((r) => setTimeout(r, 100)))
}

describe('ConfigureStep', () => {
    afterEach(() => {
        cleanup()
    })

    it('never renders the previous destination fields after the destination changes', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_functions/': { results: [], next: null },
                '/api/projects/:team_id/hog_function_templates/:id': (req) => {
                    const id = req.params.id as string
                    return [
                        200,
                        {
                            id,
                            type: 'internal_destination',
                            name: id,
                            status: 'stable',
                            free: true,
                            code: 'return event',
                            code_language: 'hog',
                            inputs_schema: [
                                { key: 'target', type: 'string', label: TEMPLATE_FIELD_LABELS[id], required: true },
                            ],
                        },
                    ]
                },
            },
        })
        initKeaTests()
        const logic = renderConfigureStep()

        act(() => {
            logic.actions.setDestinationKey('slack')
            logic.actions.setTriggerKey('error-tracking-issue-created')
        })
        await settle()
        expect(screen.getByText('Slack channel')).toBeInTheDocument()

        act(() => logic.actions.setDestinationKey('github'))
        expect(screen.queryByText('Slack channel')).not.toBeInTheDocument()
        expect(screen.queryByText('Create alert')).not.toBeInTheDocument()

        act(() => logic.actions.setTriggerKey('error-tracking-issue-created'))
        await settle()
        expect(screen.getByText('GitHub repository')).toBeInTheDocument()

        logic.unmount()
    })

    it('offers a retry when the destination settings fail to load', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_functions/': { results: [], next: null },
                '/api/projects/:team_id/hog_function_templates/:id': () => [500, {}],
            },
        })
        initKeaTests()
        const logic = renderConfigureStep()

        act(() => {
            logic.actions.setDestinationKey('slack')
            logic.actions.setTriggerKey('error-tracking-issue-created')
        })
        await settle()

        expect(screen.getByText('Could not load the settings for this destination.')).toBeInTheDocument()
        expect(screen.getAllByRole('button', { name: 'Try again' }).length).toBeGreaterThan(0)

        logic.unmount()
    })
})
