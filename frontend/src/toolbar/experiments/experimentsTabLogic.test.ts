import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { EXPERIMENT_TARGET_SELECTOR } from 'lib/actionUtils'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

import { experimentsLogic } from './experimentsLogic'
import { experimentsTabLogic } from './experimentsTabLogic'

const web_experiments = [
    {
        id: 1,
        name: 'Test Experiment 1',
        variants: {
            control: {
                transforms: [],
            },
        },
    },
    {
        id: 2,
        name: 'Test Experiment 2',
        variants: {
            control: {
                transforms: [],
            },
            test: {
                transforms: [
                    {
                        html: '<b> Hello world! </b>',
                        selector: 'h1',
                    },
                ],
            },
            test2: {
                transforms: [
                    {
                        html: '<b> Goodbye world! </b>',
                        selector: 'h1',
                    },
                ],
            },
        },
    },
]

global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ results: web_experiments }),
    } as any as Response)
)
describe('experimentsTabLogic', () => {
    let theExperimentsTabLogic: ReturnType<typeof experimentsTabLogic.build>
    let theExperimentsLogic: ReturnType<typeof experimentsLogic.build>
    let theToolbarLogic: ReturnType<typeof toolbarLogic.build>
    let theToolbarConfigLogic: ReturnType<typeof toolbarConfigLogic.build>

    beforeEach(() => {
        const { lemonToast } = jest.requireMock('lib/lemon-ui/LemonToast/LemonToast')
        ;(lemonToast.success as jest.Mock).mockClear()
        ;(lemonToast.error as jest.Mock).mockClear()
        useMocks({
            get: {
                '/api/projects/:team/web_experiments/': () => web_experiments,
            },
            post: {
                '/api/projects/@current/web_experiments/': () => ({
                    id: 3,
                    name: 'New Web Experiment',
                }),
            },
            patch: {
                '/api/projects/@current/web_experiments/1': () => ({
                    id: 3,
                    name: 'Updated web experiment',
                }),
            },
        })
        initKeaTests()

        theExperimentsLogic = experimentsLogic()
        theExperimentsLogic.mount()

        theExperimentsTabLogic = experimentsTabLogic()
        theExperimentsTabLogic.mount()

        theToolbarLogic = toolbarLogic()
        theToolbarLogic.mount()

        theToolbarConfigLogic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
        theToolbarConfigLogic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(theExperimentsTabLogic).toMount([router, experimentsLogic, toolbarConfigLogic])
        })
    })

    describe('selecting experiments', () => {
        it('can select an experiment', async () => {
            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.selectExperiment(1)
            })
                .toMatchValues({
                    selectedExperimentId: 1,
                })
                .toDispatchActions(['selectExperiment'])
        })

        it('can deselect an experiment', async () => {
            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.selectExperiment(null)
            })
                .toMatchValues({
                    selectedExperimentId: null,
                })
                .toDispatchActions(['selectExperiment'])
        })

        it('can create a new experiment', async () => {
            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.selectExperiment('new')
            })
                .toMatchValues({
                    experimentForm: {
                        name: '',
                        variants: {
                            control: {
                                transforms: [],
                                rollout_percentage: 50,
                            },
                            test: {
                                is_new: true,
                                transforms: [{}],
                                rollout_percentage: 50,
                            },
                        },
                        original_html_state: {},
                    },
                })
                .toDispatchActions(['selectExperiment'])
        })

        it('can add a new variant', async () => {
            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.selectExperiment(1)
                theExperimentsTabLogic.actions.addNewVariant()
            })
                .toMatchValues({
                    experimentForm: {
                        name: 'Test Experiment 1',
                        variants: {
                            control: {
                                transforms: [],
                                rollout_percentage: 50,
                            },
                            'variant #1': {
                                transforms: [{}],
                                rollout_percentage: 50,
                                is_new: true,
                                conditions: null,
                            },
                        },
                        original_html_state: {},
                    },
                })
                .toDispatchActions(['selectExperiment', 'addNewVariant'])
        })

        it('can remove an existing variant', async () => {
            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.selectExperiment(1)
                theExperimentsTabLogic.actions.removeVariant('variant #1')
            })
                .toMatchValues({
                    experimentForm: {
                        name: 'Test Experiment 1',
                        variants: {
                            control: {
                                transforms: [],
                                rollout_percentage: 100,
                            },
                        },
                        original_html_state: {},
                    },
                })
                .toDispatchActions(['selectExperiment'])
        })
    })

    describe('creating experiments', () => {
        it('can create a new experiment', async () => {
            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.newExperiment()
                theExperimentsTabLogic.actions.setExperimentFormValue('name', 'New Test Experiment')
                theExperimentsTabLogic.actions.submitExperimentForm()
            })
                .toMatchValues({
                    experimentForm: {
                        name: 'New Test Experiment',
                        variants: {
                            control: {
                                transforms: [],
                                rollout_percentage: 50,
                            },
                            test: {
                                is_new: true,
                                transforms: [{}],
                                rollout_percentage: 50,
                            },
                        },
                        original_html_state: {},
                    },
                })
                .toDispatchActions(['newExperiment', 'setExperimentFormValue', 'submitExperimentForm'])
        })
    })

    describe('selecting html elements', () => {
        it('can highlight all elements on a page', async () => {
            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.selectExperiment(1)
                theExperimentsTabLogic.actions.inspectForElementWithIndex('test', 'all-elements', 0)
            })
                .toDispatchActions(['selectExperiment', 'inspectForElementWithIndex'])
                .toMatchValues({
                    elementSelector: EXPERIMENT_TARGET_SELECTOR,
                })
        })

        it('can highlight only images on a page', async () => {
            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.selectExperiment(1)
                theExperimentsTabLogic.actions.inspectForElementWithIndex('test', 'images', 0)
            })
                .toDispatchActions(['selectExperiment', 'inspectForElementWithIndex'])
                .toMatchValues({
                    elementSelector: 'img',
                })
        })

        it('can highlight only buttons on a page', async () => {
            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.selectExperiment(1)
                theExperimentsTabLogic.actions.inspectForElementWithIndex('test', 'buttons', 0)
            })
                .toDispatchActions(['selectExperiment', 'inspectForElementWithIndex'])
                .toMatchValues({
                    elementSelector: 'input[type="button"],button',
                })
        })

        it('can highlight only headers on a page', async () => {
            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.selectExperiment(1)
                theExperimentsTabLogic.actions.inspectForElementWithIndex('test', 'headers', 0)
            })
                .toDispatchActions(['selectExperiment', 'inspectForElementWithIndex'])
                .toMatchValues({
                    elementSelector: 'h1,h2,h3,h4,h5,h6',
                })
        })
    })

    describe('form submission error handling', () => {
        const savedFetch = global.fetch

        afterEach(() => {
            global.fetch = savedFetch
        })

        it('shows error toast when API returns error with detail', async () => {
            const { lemonToast } = jest.requireMock('lib/lemon-ui/LemonToast/LemonToast')

            global.fetch = jest.fn(() =>
                Promise.resolve({
                    ok: false,
                    status: 400,
                    json: () => Promise.resolve({ detail: 'Invalid experiment config' }),
                } as any as Response)
            )

            theExperimentsTabLogic.actions.newExperiment()
            theExperimentsTabLogic.actions.setExperimentFormValue('name', 'Bad Experiment')

            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.submitExperimentForm()
            }).delay(0)

            expect(lemonToast.error).toHaveBeenCalledWith('Experiment save failed: Invalid experiment config')
        })

        it('shows generic error when API returns error and json parsing fails', async () => {
            const { lemonToast } = jest.requireMock('lib/lemon-ui/LemonToast/LemonToast')

            global.fetch = jest.fn(() =>
                Promise.resolve({
                    ok: false,
                    status: 500,
                    json: () => Promise.reject(new Error('parse error')),
                } as any as Response)
            )

            theExperimentsTabLogic.actions.newExperiment()
            theExperimentsTabLogic.actions.setExperimentFormValue('name', 'Server Error Experiment')

            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.submitExperimentForm()
            }).delay(0)

            expect(lemonToast.error).toHaveBeenCalledWith('Experiment save failed: Request failed: 500')
        })

        it('handles network error gracefully', async () => {
            const { lemonToast } = jest.requireMock('lib/lemon-ui/LemonToast/LemonToast')

            global.fetch = jest.fn(() => Promise.reject(new Error('Network error')))

            theExperimentsTabLogic.actions.newExperiment()
            theExperimentsTabLogic.actions.setExperimentFormValue('name', 'Network Error Experiment')

            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.submitExperimentForm()
            }).delay(0)

            expect(lemonToast.error).toHaveBeenCalledWith('Experiment save failed: Network error')
        })
    })

    describe('editing experiments', () => {
        it('can edit an existing experiment', async () => {
            await expectLogic(theExperimentsTabLogic, () => {
                theExperimentsTabLogic.actions.selectExperiment(1)
                theExperimentsTabLogic.actions.setExperimentFormValue('name', 'Updated Experiment 1')
                theExperimentsTabLogic.actions.submitExperimentForm()
            })
                .toDispatchActions(['selectExperiment', 'setExperimentFormValue', 'submitExperimentForm'])
                .toMatchValues({
                    experimentForm: {
                        name: 'Updated Experiment 1',
                        variants: {
                            control: {
                                transforms: [],
                                rollout_percentage: 100,
                            },
                        },
                        original_html_state: {},
                    },
                })
        })

        it('can apply changes from a variant', async () => {
            await expectLogic(theExperimentsLogic, () => {
                theExperimentsLogic.actions.getExperiments()
            })
                .delay(0)
                .then(() => {
                    theExperimentsTabLogic.actions.selectExperiment(2)
                    theExperimentsTabLogic.actions.applyVariant('test')
                })
        })

        it('can switch between variants', async () => {
            await expectLogic(theExperimentsLogic, () => {
                theExperimentsLogic.actions.getExperiments()
            })
                .delay(0)
                .then(() => {
                    theExperimentsTabLogic.actions.selectExperiment(2)
                    theExperimentsTabLogic.actions.applyVariant('test')
                    theExperimentsTabLogic.actions.applyVariant('test2')
                })
        })
    })
})
