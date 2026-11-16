import { waitForPageToSettle } from '~/toolbar/shared/flags/flagComparison'
import { TOOLBAR_ROOT_ATTRIBUTE } from '~/toolbar/shared/utils'

const STEP_MS = 100

describe('waitForPageToSettle', () => {
    let pageElement: HTMLElement
    let toolbarRoot: HTMLElement

    beforeEach(() => {
        jest.useFakeTimers()
        pageElement = document.createElement('main')
        toolbarRoot = document.createElement('div')
        toolbarRoot.setAttribute(TOOLBAR_ROOT_ATTRIBUTE, '')
        document.body.append(pageElement, toolbarRoot)
    })

    afterEach(() => {
        pageElement.remove()
        toolbarRoot.remove()
        jest.useRealTimers()
    })

    async function settledAfterMs(mutateAtMs: number[], target: () => HTMLElement): Promise<number> {
        let settled = false
        void waitForPageToSettle(1000, 8000).then(() => (settled = true))
        for (let elapsed = 0; elapsed <= 10000; elapsed += STEP_MS) {
            if (settled) {
                return elapsed
            }
            if (mutateAtMs.includes(elapsed)) {
                target().append(document.createElement('span'))
            }
            await jest.advanceTimersByTimeAsync(STEP_MS)
        }
        throw new Error('The page never settled')
    }

    const everyHalfSecond = Array.from({ length: 20 }, (_, index) => index * 500)

    test.each([
        { scenario: 'a quiet page settles after the quiet period', mutateAtMs: [], inToolbar: false, settlesAt: 1000 },
        { scenario: 'a page change restarts the quiet period', mutateAtMs: [500], inToolbar: false, settlesAt: 1500 },
        {
            scenario: 'a page that keeps changing settles at the cap',
            mutateAtMs: everyHalfSecond,
            inToolbar: false,
            settlesAt: 8000,
        },
        {
            scenario: "the toolbar's own changes do not count",
            mutateAtMs: everyHalfSecond,
            inToolbar: true,
            settlesAt: 1000,
        },
    ])('$scenario', async ({ mutateAtMs, inToolbar, settlesAt }) => {
        await expect(settledAfterMs(mutateAtMs, () => (inToolbar ? toolbarRoot : pageElement))).resolves.toEqual(
            settlesAt
        )
    })
})
