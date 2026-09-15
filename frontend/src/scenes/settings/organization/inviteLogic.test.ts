import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'
import { dayjs } from 'lib/dayjs'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inviteLogic } from './inviteLogic'

describe('inviteLogic', () => {
    let logic: ReturnType<typeof inviteLogic.build>
    let timeSensitiveAuthentication: ReturnType<typeof timeSensitiveAuthenticationLogic.build>

    const loadUserWithSensitiveSessionExpiringIn = (minutes: number): void => {
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            sensitive_session_expires_at: dayjs().add(minutes, 'minute').toISOString(),
        })
    }

    beforeEach(() => {
        useMocks({
            post: {
                '/api/login/precheck': { status: 'completed', sso_enforcement: null, saml_available: false },
            },
        })
        initKeaTests()
        timeSensitiveAuthentication = timeSensitiveAuthenticationLogic.build()
        timeSensitiveAuthentication.mount()
        logic = inviteLogic.build()
        logic.mount()
    })

    afterEach(async () => {
        // A pending re-authentication holds a listener open until the user answers it.
        apiStatusLogic.actions.resolveSensitiveAction('failure')
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
        timeSensitiveAuthentication.unmount()
    })

    it.each([
        ['asks for re-authentication and keeps the form closed', 1, false, true],
        ['opens the form', 60, true, false],
    ])('%s when the sensitive session expires in %s minutes', (_, minutes, isVisible, showAuthenticationModal) => {
        loadUserWithSensitiveSessionExpiringIn(minutes)

        logic.actions.showInviteModal()

        expect(logic.values.isInviteModalVisible).toBe(isVisible)
        expect(timeSensitiveAuthentication.values.showAuthenticationModal).toBe(showAuthenticationModal)
    })

    it('opens the form once re-authentication succeeds', () => {
        loadUserWithSensitiveSessionExpiringIn(1)
        logic.actions.showInviteModal()
        expect(logic.values.isInviteModalVisible).toBe(false)

        apiStatusLogic.actions.resolveSensitiveAction('success')

        expect(logic.values.isInviteModalVisible).toBe(true)
    })
})
