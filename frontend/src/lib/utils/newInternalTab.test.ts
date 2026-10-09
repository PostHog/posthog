import { newInternalTab } from 'lib/utils/newInternalTab'

describe('newInternalTab', () => {
    let clickedHrefs: string[]

    beforeEach(() => {
        clickedHrefs = []
        jest.spyOn(HTMLAnchorElement.prototype, 'dispatchEvent').mockImplementation(function (this: HTMLAnchorElement) {
            clickedHrefs.push(this.getAttribute('href') ?? '')
            return true
        })
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('opens an external link as given', () => {
        newInternalTab('https://posthog.com/docs')

        expect(clickedHrefs).toEqual(['https://posthog.com/docs'])
    })

    it.each(['javascript:alert(1)', 'javascript:/api/,alert(document.cookie)', 'JaVaScRiPt:/login/,alert(1)'])(
        'opens nothing for %p',
        (path) => {
            newInternalTab(path)

            expect(clickedHrefs).toEqual([])
        }
    )
})
