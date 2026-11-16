import { navSwitchLogic } from 'lib/components/NavSwitch/navSwitchLogic'

import { initKeaTests } from '~/test/init'

import { TODAY_TOUR_STEPS, todayTourLogic } from './todayTourLogic'

type TourLogic = ReturnType<typeof todayTourLogic.build>

const clickDoneOnLastStep = (logic: TourLogic): void => {
    TODAY_TOUR_STEPS.forEach(() => logic.actions.nextTourStep())
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
})
