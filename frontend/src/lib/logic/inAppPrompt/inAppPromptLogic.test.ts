import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { inAppPromptLogic, Prompt, PromptSequence } from './inAppPromptLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { useMocks } from '~/mocks/jest'
import api from 'lib/api'
import { inAppPromptEventCaptureLogic } from './inAppPromptEventCaptureLogic'

const config = {
    sequences: [
        {
            key: 'experiment-events-product-tour',
            prompts: [
                {
                    step: 0,
                    type: 'tooltip',
                    text: "Welcome! We'd like to give you a quick tour!",
                    placement: 'top-start',
                    buttons: [{ action: 'skip', label: 'Skip tutorial' }],
                    reference: 'experiment-events-product-tour',
                    icon: 'live-events',
                },
                {
                    step: 1,
                    type: 'tooltip',
                    text: "Here you can see all events from the past 12 months. Things look a bit quiet, so let's turn on automatic refresh to see events in real-time.",
                    placement: 'top-start',
                    reference: 'experiment-events-product-tour',
                    icon: 'live-events',
                },
                {
                    step: 2,
                    type: 'tooltip',
                    text: "If you aren't seeing the data you expect then you can always ask for help. For now, lets analyze some data. Click 'Dashboards' in the sidebar.",
                    placement: 'top-start',
                    buttons: [{ url: 'https://posthog.com/questions', label: 'Ask for help' }],
                    icon: 'live-events',
                    reference: 'experiment-events-product-tour',
                },
            ],
            rule: { path: '/events' },
            type: 'product-tour',
        },
        {
            key: 'experiment-dashboards-product-tour',
            prompts: [
                {
                    step: 0,
                    type: 'tooltip',
                    text: "In PostHog, you analyse data with Insights which can be added to Dashboards to aid collaboration. Let's create a new Dashboard by selecting 'New Dashboard'. ",
                    placement: 'top-start',
                    icon: 'dashboard',
                    reference: 'experiment-dashboards-product-tour',
                },
            ],
            rule: { path: '/dashboard' },
            type: 'product-tour',
        },
    ],
    state: {
        'experiment-events-product-tour': {
            key: 'experiment-events-product-tour',
            step: 0,
            completed: false,
            dismissed: false,
            last_updated_at: '2022-07-26T16:32:55.153Z',
        },
    },
}

describe('inAppPromptLogic', () => {
    let logic: ReturnType<typeof inAppPromptLogic.build>

    beforeEach(async () => {
        localStorage.clear()
        jest.spyOn(api, 'update')
        useMocks({
            patch: {
                '/api/projects/:team/prompts/my_prompts/': config,
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        logic = inAppPromptLogic()
        logic.mount()
        await expectLogic(logic).toMount([inAppPromptEventCaptureLogic])
        await expectLogic(logic, () => {
            logic.actions.syncState({ forceRun: true })
        })
            .toDispatchActions(['setUserState', 'setSequences', 'findValidSequences', 'setValidSequences'])
            .toMatchValues({
                sequences: config.sequences,
                userState: config.state,
                validSequences: [],
            })
    })

    afterEach(() => logic.unmount())

    it('changes route and correctly triggers an unseen sequence', async () => {
        router.actions.push(urls.dashboards())
        await expectLogic(logic)
            .toDispatchActions(['closePrompts', 'findValidSequences', 'setValidSequences'])
            .toMatchValues({
                validSequences: [
                    {
                        sequence: config.sequences[1],
                        state: {
                            step: 0,
                        },
                    },
                ],
            })
        await expectLogic(logic)
            .toDispatchActions([
                'runFirstValidSequence',
                'closePrompts',
                logic.actionCreators.runSequence(config.sequences[1] as PromptSequence, 0),
                logic.actionCreators.runPrompt(config.sequences[1].prompts[0] as Prompt),
                'tooltip',
            ])
            .toMatchValues({
                currentSequence: config.sequences[1],
                currentStep: 0,
                isPromptVisible: true,
            })
    })

    describe('runs a sequence left unfinished', () => {
        beforeEach(async () => {
            router.actions.push(urls.events())
            await expectLogic(logic)
                .toDispatchActions(['closePrompts', 'findValidSequences', 'setValidSequences'])
                .toMatchValues({
                    validSequences: [
                        {
                            sequence: config.sequences[0],
                            state: {
                                step: 1,
                                completed: false,
                                dismissed: false,
                            },
                        },
                    ],
                })
            await expectLogic(logic)
                .toDispatchActions([
                    'runFirstValidSequence',
                    'closePrompts',
                    logic.actionCreators.runSequence(config.sequences[0] as PromptSequence, 1),
                    logic.actionCreators.runPrompt(config.sequences[0].prompts[1] as Prompt),
                    'tooltip',
                ])
                .toMatchValues({
                    currentSequence: config.sequences[0],
                    currentStep: 1,
                    isPromptVisible: true,
                })
        })
        it('can dismiss a sequence', async () => {
            await expectLogic(logic, () => {
                logic.actions.dismissSequence()
            })
                .toDispatchActions([
                    logic.actionCreators.updatePromptState({ dismissed: true }),
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptSequenceDismissed(
                        config.sequences[0].key,
                        1,
                        3
                    ),
                ])
                .toMatchValues({
                    isPromptVisible: false,
                })
        })
        it('can complete a sequence then dismiss it', async () => {
            await expectLogic(logic, () => {
                logic.actions.nextPrompt()
            })
                .toDispatchActions([
                    logic.actionCreators.runSequence(config.sequences[0] as PromptSequence, 2),
                    logic.actionCreators.runPrompt(config.sequences[0].prompts[2] as Prompt),
                    logic.actionCreators.updatePromptState({ completed: true }),
                ])
                .toDispatchActionsInAnyOrder([
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptForward(config.sequences[0].key, 2, 3),
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptSequenceCompleted(
                        config.sequences[0].key,
                        2,
                        3
                    ),
                ])
                .toMatchValues({
                    currentStep: 2,
                })
            await expectLogic(logic, () => {
                logic.actions.dismissSequence()
            })
                .toDispatchActions(['clearSequence'])
                .toNotHaveDispatchedActions([
                    logic.actionCreators.updatePromptState({ dismissed: true }),
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptSequenceDismissed(
                        config.sequences[0].key,
                        2,
                        3
                    ),
                ])
        })
        it('can skip the tutorials', async () => {
            await expectLogic(logic, () => {
                logic.actions.promptAction('skip')
            })
                .toDispatchActions([
                    'closePrompts',
                    'skipTutorial',
                    inAppPromptEventCaptureLogic.actionCreators.reportTutorialSkipped(),
                ])
                .toMatchValues({
                    hasSkippedTutorial: true,
                })
        })
        it('can go to previous prompt', async () => {
            await expectLogic(logic, () => {
                logic.actions.previousPrompt()
            })
                .toDispatchActions([
                    logic.actionCreators.runSequence(config.sequences[0] as PromptSequence, 0),
                    logic.actionCreators.runPrompt(config.sequences[0].prompts[0] as Prompt),
                ])
                .toDispatchActionsInAnyOrder([
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptBackward(config.sequences[0].key, 0, 3),
                ])
                .toMatchValues({
                    currentStep: 0,
                })
        })
    })
})
