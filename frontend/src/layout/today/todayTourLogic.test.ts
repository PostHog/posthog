import { navSwitchLogic } from 'lib/components/NavSwitch/navSwitchLogic'
import { FEATURE_FLAGS } from 'lib/constants'

import { initKeaTests } from '~/test/init'

import { todayTourLogic, tourStepsForFlags } from './todayTourLogic'

type TourLogic = ReturnType<typeof todayTourLogic.build>

const clickDoneOnLastStep = (logic: TourLogic): void => {
    logic.values.tour?.steps.forEach(() => logic.actions.nextTourStep())
}

const closeTourEarly = (logic: TourLogic): void => {
    logic.actions.nextTourStep()
    logic.actions.endTour()
}

describe('todayTourLogic', () => {
    let tourLogic: TourLogic
    let switchLogic: ReturnType<typeof navSwitchLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        tourLogic = todayTourLogic()
        tourLogic.mount()
        switchLogic = navSwitchLogic()
        switchLogic.mount()
        switchLogic.actions.setNewNavDialogOpen(true)
        tourLogic.actions.startTour({ x: 0, y: 0 })
    })

    test.each([
        { ending: 'clicking Done on the last step', endTheTour: clickDoneOnLastStep, finished: true },
        { ending: 'closing the tour early', endTheTour: closeTourEarly, finished: false },
    ])('ending the tour by $ending reopens the dialog, finished: $finished', ({ endTheTour, finished }) => {
        endTheTour(tourLogic)

        expect(tourLogic.values.tourActive).toBe(false)
        expect(switchLogic.values.newNavDialogOpen).toBe(true)
        expect(tourLogic.values.tourJustCompleted).toBe(finished)
    })

    test.each([
        { closing: 'a dialog button', close: () => switchLogic.actions.setNewNavDialogOpen(false) },
        { closing: 'a dismissal', close: () => switchLogic.actions.dismissNewNavDialog() },
    ])('closing the finished-tour dialog with $closing brings back the usual copy', ({ close }) => {
        clickDoneOnLastStep(tourLogic)
        close()
        switchLogic.actions.setNewNavDialogOpen(true)

        expect(tourLogic.values.tourCompleted).toBe(true)
        expect(tourLogic.values.tourJustCompleted).toBe(false)
    })

    test('a started tour keeps the steps for the panes its flags show', () => {
        expect(tourLogic.values.tour?.steps.map((step) => step.pane)).toEqual([
            'home',
            'analytics',
            'people',
            'products',
            'settings',
        ])
    })

    test.each([
        { flags: {}, panes: ['home', 'analytics', 'people', 'products', 'settings'] },
        {
            flags: {
                [FEATURE_FLAGS.RELEASES_AREA]: true,
                [FEATURE_FLAGS.MONITOR_AREA]: true,
                [FEATURE_FLAGS.DATA_AREA]: true,
            },
            panes: ['home', 'analytics', 'people', 'release', 'monitor', 'automate', 'data', 'products', 'settings'],
        },
    ])('the tour visits only the panes the flags show: $panes', ({ flags, panes }) => {
        expect(tourStepsForFlags(flags).map((step) => step.pane)).toEqual(panes)
    })
})
