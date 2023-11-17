import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { inAppPromptLogic, PromptConfig, PromptUserState } from './inAppPromptLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { useMocks } from '~/mocks/jest'
import api from 'lib/api'
import { inAppPromptEventCaptureLogic } from './inAppPromptEventCaptureLogic'

const configProductTours: PromptConfig & { state: PromptUserState } = {
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
                    reference: 'tooltip-test',
                    icon: 'live-events',
                },
                {
                    step: 1,
                    type: 'tooltip',
                    text: "Here you can see all events from the past 12 months. Things look a bit quiet, so let's turn on automatic refresh to see events in real-time.",
                    placement: 'top-start',
                    reference: 'tooltip-test',
                    icon: 'live-events',
                },
                {
                    step: 2,
                    type: 'tooltip',
                    text: "If you aren't seeing the data you expect then you can always ask for help. For now, lets analyze some data. Click 'Dashboards' in the sidebar.",
                    placement: 'top-start',
                    buttons: [{ url: 'https://posthog.com/questions', label: 'Ask for help' }],
                    icon: 'live-events',
                    reference: 'tooltip-test',
                },
            ],
            path_match: ['/events'],
            path_exclude: [],
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
                    reference: 'tooltip-test',
                },
                {
                    step: 1,
                    type: 'tooltip',
                    text: "In PostHog, you analyse data with Insights which can be added to Dashboards to aid collaboration. Let's create a new Dashboard by selecting 'New Dashboard'. ",
                    placement: 'top-start',
                    icon: 'dashboard',
                    reference: 'tooltip-test',
                },
            ],
            path_match: ['/dashboard'],
            path_exclude: ['/dashboard/*'],
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
        'experiment-dashboards-product-tour': {
            key: 'experiment-dashboards-product-tour',
            step: null,
            completed: false,
            dismissed: false,
            last_updated_at: '2022-07-26T16:32:55.153Z',
        },
    },
}

const configOptIn: PromptConfig & { state: PromptUserState } = {
    sequences: [
        {
            key: 'experiment-one-off-intro',
            prompts: [
                {
                    step: 0,
                    type: 'tooltip',
                    text: 'This is welcome message to ask users to opt-in',
                    placement: 'top-start',
                    icon: 'dashboard',
                    reference: 'tooltip-test',
                },
            ],
            path_match: ['/*'],
            path_exclude: [],
            type: 'one-off',
        },
        {
            key: 'experiment-one-off',
            prompts: [
                {
                    step: 0,
                    type: 'tooltip',
                    text: 'This is a one off prompt that requires opt-in',
                    placement: 'top-start',
                    icon: 'dashboard',
                    reference: 'tooltip-test',
                },
            ],
            path_match: ['/*'],
            path_exclude: [],
            requires_opt_in: true,
            type: 'one-off',
        },
    ],
    state: {
        'experiment-one-off-intro': {
            key: 'experiment-one-off-intro',
            step: null,
            completed: false,
            dismissed: false,
            last_updated_at: '2022-07-26T16:32:55.153Z',
        },
        'experiment-one-off': {
            key: 'experiment-one-off',
            step: null,
            completed: false,
            dismissed: false,
            last_updated_at: '2022-07-26T16:32:55.153Z',
        },
    },
}

describe('inAppPromptLogic', () => {
    let logic: ReturnType<typeof inAppPromptLogic.build>

    describe('opt-in prompts', () => {
        beforeEach(async () => {
            const div = document.createElement('div')
            div['data-attr'] = 'tooltip-test'
            const spy = jest.spyOn(document, 'querySelector')
            spy.mockReturnValue(div)
            jest.spyOn(api, 'update')
            useMocks({
                patch: {
                    '/api/prompts/my_prompts/': configOptIn,
                },
            })
            localStorage.clear()
            initKeaTests()
            featureFlagLogic.mount()
            logic = inAppPromptLogic()
            logic.mount()
            await expectLogic(logic).toMount([inAppPromptEventCaptureLogic])
        })

        afterEach(() => logic.unmount())

        it('correctly opts in', async () => {
            logic.actions.optInProductTour()
            await expectLogic(logic).toMatchValues({
                canShowProductTour: true,
            })
        })

        it('correctly opts out when skipping', async () => {
            logic.actions.optInProductTour()
            await expectLogic(logic, () => {
                logic.actions.promptAction('skip')
            })
                .toDispatchActions([
                    'closePrompts',
                    'optOutProductTour',
                    inAppPromptEventCaptureLogic.actionCreators.reportProductTourSkipped(),
                ])
                .toMatchValues({
                    canShowProductTour: false,
                })
        })

        it('correctly sets valid sequences respecting opt-out and opt-in', async () => {
            logic.actions.optOutProductTour()
            await expectLogic(logic, () => {
                logic.actions.syncState({ forceRun: true })
            })
                .toDispatchActions(['setSequences', 'findValidSequences', 'setValidSequences'])
                .toMatchValues({
                    sequences: configOptIn.sequences,
                    userState: configOptIn.state,
                    canShowProductTour: false,
                    validSequences: [
                        {
                            sequence: configOptIn.sequences[0],
                            state: {
                                step: 0,
                                completed: false,
                            },
                        },
                    ],
                })

            logic.actions.optInProductTour()
            logic.actions.findValidSequences()
            await expectLogic(logic).toMatchValues({
                canShowProductTour: true,
                validSequences: [
                    {
                        sequence: configOptIn.sequences[0],
                        state: {
                            step: 0,
                            completed: false,
                        },
                    },
                    {
                        sequence: configOptIn.sequences[1],
                        state: {
                            step: 0,
                            completed: false,
                        },
                    },
                ],
            })
        })
    })

    describe('product tours', () => {
        beforeEach(async () => {
            const div = document.createElement('div')
            div['data-attr'] = 'tooltip-test'
            const spy = jest.spyOn(document, 'querySelector')
            spy.mockReturnValue(div)
            jest.spyOn(api, 'update')
            useMocks({
                patch: {
                    '/api/prompts/my_prompts/': configProductTours,
                },
            })
            localStorage.clear()
            initKeaTests()
            featureFlagLogic.mount()
            logic = inAppPromptLogic()
            logic.mount()
            logic.actions.optInProductTour()
            await expectLogic(logic).toMount([inAppPromptEventCaptureLogic])
            await expectLogic(logic, () => {
                logic.actions.syncState({ forceRun: true })
            })
                .toDispatchActions(['setUserState', 'setSequences', 'findValidSequences', 'setValidSequences'])
                .toMatchValues({
                    sequences: configProductTours.sequences,
                    userState: configProductTours.state,
                    validSequences: [],
                })
        })

        afterEach(() => logic.unmount())

        it('changes route and dismissed the sequence in an excluded path', async () => {
            router.actions.push(urls.dashboard('my-dashboard'))
            await expectLogic(logic)
                .toDispatchActions(['closePrompts', 'findValidSequences', 'setValidSequences', 'runFirstValidSequence'])
                .toNotHaveDispatchedActions(['runSequence'])
        })

        it('changes route and correctly triggers an unseen sequence', async () => {
            router.actions.push(urls.dashboards())
            await expectLogic(logic)
                .toDispatchActions(['closePrompts', 'findValidSequences', 'setValidSequences'])
                .toMatchValues({
                    validSequences: [
                        {
                            sequence: configProductTours.sequences[1],
                            state: {
                                step: 0,
                                completed: false,
                            },
                        },
                    ],
                })
                .toDispatchActions([
                    'closePrompts',
                    logic.actionCreators.runSequence(configProductTours.sequences[1], 0),
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptShown(
                        'tooltip',
                        configProductTours.sequences[1].key,
                        0,
                        2
                    ),
                    'promptShownSuccessfully',
                ])
                .toMatchValues({
                    currentSequence: configProductTours.sequences[1],
                    currentStep: 0,
                })
        })

        it('can dismiss a sequence', async () => {
            router.actions.push(urls.dashboards())
            await expectLogic(logic).toDispatchActions(['promptShownSuccessfully']).toMatchValues({
                isPromptVisible: true,
            })
            await expectLogic(logic, () => {
                logic.actions.dismissSequence()
            })
                .toDispatchActions([
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptSequenceDismissed(
                        configProductTours.sequences[1].key,
                        0,
                        2
                    ),
                ])
                .toMatchValues({
                    isPromptVisible: false,
                })
        })

        it('can complete sequence, then go back, then dismiss it', async () => {
            router.actions.push(urls.dashboards())
            await expectLogic(logic).toDispatchActions(['promptShownSuccessfully']).toMatchValues({
                isPromptVisible: true,
            })
            await expectLogic(logic, () => {
                logic.actions.nextPrompt()
            })
                .toDispatchActions([
                    logic.actionCreators.runSequence(configProductTours.sequences[1], 1),
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptForward(
                        configProductTours.sequences[1].key,
                        1,
                        2
                    ),
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptSequenceCompleted(
                        configProductTours.sequences[1].key,
                        1,
                        2
                    ),
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptShown(
                        'tooltip',
                        configProductTours.sequences[1].key,
                        1,
                        2
                    ),
                    'promptShownSuccessfully',
                ])
                .toMatchValues({
                    currentStep: 1,
                })
            await expectLogic(logic, () => {
                logic.actions.previousPrompt()
            })
                .toDispatchActions([
                    logic.actionCreators.runSequence(configProductTours.sequences[1], 0),
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptBackward(
                        configProductTours.sequences[1].key,
                        0,
                        2
                    ),
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptShown(
                        'tooltip',
                        configProductTours.sequences[1].key,
                        0,
                        2
                    ),
                    'promptShownSuccessfully',
                ])
                .toMatchValues({
                    currentStep: 0,
                })
            await expectLogic(logic, () => {
                logic.actions.dismissSequence()
            })
                .toDispatchActions(['clearSequence'])
                .toNotHaveDispatchedActions([
                    inAppPromptEventCaptureLogic.actionCreators.reportPromptSequenceDismissed(
                        configProductTours.sequences[0].key,
                        1,
                        2
                    ),
                ])
        })

        it('does not run a sequence left unfinished', async () => {
            router.actions.push(urls.events())
            await expectLogic(logic).toNotHaveDispatchedActions(['promptShownSuccessfully']).toMatchValues({
                isPromptVisible: false,
            })
        })
    })
})
