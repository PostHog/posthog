import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'

import { initKeaTests } from '~/test/init'

import { todayHelpMenuRedirectLogic } from './todayHelpMenuRedirectLogic'

describe('todayHelpMenuRedirectLogic', () => {
    const DESKTOP = 1280
    const PHONE = 390
    const openFromNavSwitch = (): void => helpMenuLogic.actions.setHelpMenuOpen(true)
    const openFromShortcut = (): void => helpMenuLogic.actions.toggleHelpMenu()
    let originalWidth: number

    beforeEach(() => {
        originalWidth = window.innerWidth
        initKeaTests()
    })

    afterEach(() => {
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
    })

    test.each([
        { opener: 'the nav switch', openHelp: openFromNavSwitch, width: DESKTOP, accountOpen: true },
        { opener: 'the nav switch', openHelp: openFromNavSwitch, width: PHONE, accountOpen: false },
        { opener: 'the ? shortcut', openHelp: openFromShortcut, width: DESKTOP, accountOpen: true },
        { opener: 'the ? shortcut', openHelp: openFromShortcut, width: PHONE, accountOpen: false },
    ])(
        'opening help from $opener at $width px opens the account menu: $accountOpen',
        ({ openHelp, width, accountOpen }) => {
            Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
            todayHelpMenuRedirectLogic.mount()
            newAccountMenuLogic.mount()

            openHelp()

            expect(newAccountMenuLogic.values.isAccountMenuOpen).toBe(accountOpen)
            // The phone layout opens the help menu itself, as its More sheet.
            expect(helpMenuLogic.values.isHelpMenuOpen).toBe(!accountOpen)
        }
    )
})
