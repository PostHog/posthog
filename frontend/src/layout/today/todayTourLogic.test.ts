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
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    test.each([
        { ending: 'clicking Done on the last step', endTheTour: clickDoneOnLastStep, dialogOpen: false },
        { ending: 'closing the tour early', endTheTour: closeTourEarly, dialogOpen: true },
    ])('ending the tour by $ending leaves the dialog open: $dialogOpen', ({ endTheTour, dialogOpen }) => {
        const tourLogic = todayTourLogic()
        tourLogic.mount()
        const switchLogic = navSwitchLogic()
        switchLogic.mount()

        switchLogic.actions.setNewNavDialogOpen(true)
        tourLogic.actions.startTour({ x: 0, y: 0 })
        endTheTour(tourLogic)

        expect(tourLogic.values.tourActive).toBe(false)
        expect(tourLogic.values.tourCompleted).toBe(!dialogOpen)
        expect(switchLogic.values.newNavDialogOpen).toBe(dialogOpen)
    })
})
