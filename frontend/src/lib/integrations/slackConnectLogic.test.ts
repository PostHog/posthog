import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { integrationsLogic } from './integrationsLogic'
import { slackConnectLogic } from './slackConnectLogic'

const OTHER_MEMBER = { ...MOCK_DEFAULT_BASIC_USER, id: 999, uuid: 'other-member-uuid' }

const integration = (
    id: number,
    kind: IntegrationType['kind'],
    createdBy: IntegrationType['created_by'] = MOCK_DEFAULT_BASIC_USER
): IntegrationType =>
    ({
        id,
        kind,
        display_name: `Workspace ${id}`,
        icon_url: '',
        config: {},
        errors: '',
        created_by: createdBy,
    }) as IntegrationType

describe('slackConnectLogic', () => {
    let onConnected: jest.Mock
    let logic: ReturnType<typeof slackConnectLogic.build>

    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team_id/integrations/': () => [200, { results: [] }] } })
        initKeaTests()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        integrationsLogic.mount()
        onConnected = jest.fn()
        logic = slackConnectLogic({ connectKey: 'test', onConnected })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('selects the workspace that appears after the click and stops polling', async () => {
        integrationsLogic.actions.loadIntegrationsSuccess([integration(1, 'slack')])
        expect(onConnected).not.toHaveBeenCalled()

        await expectLogic(logic, () => logic.actions.connectSlackClicked()).toMatchValues({ waitingForSlack: true })
        expect(integrationsLogic.values.pollingSubscribers).toBe(1)

        integrationsLogic.actions.loadIntegrationsSuccess([integration(1, 'slack'), integration(2, 'github')])
        expect(onConnected).not.toHaveBeenCalled()

        integrationsLogic.actions.loadIntegrationsSuccess([
            integration(1, 'slack'),
            integration(2, 'github'),
            integration(3, 'slack'),
        ])

        expect(onConnected).toHaveBeenCalledWith(3)
        expect(logic.values.waitingForSlack).toBe(false)
        expect(integrationsLogic.values.pollingSubscribers).toBe(0)
    })

    it.each([
        {
            name: 'a workspace another member adds while this user connects',
            before: [integration(1, 'slack')],
            after: [integration(1, 'slack'), integration(2, 'slack', OTHER_MEMBER)],
        },
        {
            name: 'an existing workspace when the list had not loaded at the click',
            before: null,
            after: [integration(1, 'slack')],
        },
    ])('does not select $name', ({ before, after }) => {
        integrationsLogic.actions.loadIntegrationsSuccess(before as IntegrationType[])
        logic.actions.connectSlackClicked()

        integrationsLogic.actions.loadIntegrationsSuccess(after)

        expect(onConnected).not.toHaveBeenCalled()
        expect(logic.values.waitingForSlack).toBe(true)
    })

    it('stops polling when the banner unmounts before Slack connects', () => {
        logic.actions.connectSlackClicked()
        logic.actions.connectSlackClicked()
        expect(integrationsLogic.values.pollingSubscribers).toBe(1)

        logic.unmount()

        expect(integrationsLogic.values.pollingSubscribers).toBe(0)
        logic.mount()
    })
})
