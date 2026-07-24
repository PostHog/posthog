import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { personEmailsLogic } from './personEmailsLogic'

const PERSON_ID = 'abc-123'
const EMAILS_URL = `/api/projects/${MOCK_TEAM_ID}/persons/${PERSON_ID}/emails/`

describe('personEmailsLogic', () => {
    let logic: ReturnType<typeof personEmailsLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('falls back to an empty list when the emails endpoint 404s for an unresolvable person', async () => {
        useMocks({
            get: {
                [EMAILS_URL]: [404, { detail: 'Not found.' }],
            },
        })
        logic = personEmailsLogic({ teamId: MOCK_TEAM_ID, personId: PERSON_ID })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadEmails()
        })
            .toDispatchActions(['loadEmailsSuccess'])
            .toMatchValues({ emails: [] })
    })

    it('surfaces non-404 errors instead of swallowing them', async () => {
        useMocks({
            get: {
                [EMAILS_URL]: [500, { detail: 'Server error' }],
            },
        })
        logic = personEmailsLogic({ teamId: MOCK_TEAM_ID, personId: PERSON_ID })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadEmails()
        }).toDispatchActions(['loadEmailsFailure'])
    })
})
