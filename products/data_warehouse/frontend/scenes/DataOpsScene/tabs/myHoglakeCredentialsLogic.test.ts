import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import * as dwApi from 'products/data_warehouse/frontend/generated/api'
import type {
    HoglakeCredentialIssuedApi,
    MyHoglakeCredentialListResponseApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { myHoglakeCredentialsLogic } from './myHoglakeCredentialsLogic'

const OTHER_PROJECT = 424242

function list(currentTeamId: number): MyHoglakeCredentialListResponseApi {
    return {
        hoglake_credentials: [
            {
                client_id: 'hlc_0123456789abcdef01234567',
                name: 'laptop',
                scope: 'read',
                kind: 'team',
                team_ids: [currentTeamId],
                created_at: '2026-11-01T00:00:00Z',
                last_rotated_at: '2026-11-01T00:00:00Z',
                expires_at: '2027-02-01T00:00:00Z',
            },
        ],
        connect: { catalog: 'org-1', token_url: 'https://hogtower-oauth.example.test/oauth/token' },
        projects: [
            { id: currentTeamId, name: 'Prod', access: 'write' },
            { id: OTHER_PROJECT, name: 'Staging', access: 'read' },
        ],
    }
}

const ISSUED: HoglakeCredentialIssuedApi = {
    client_id: 'hlc_fedcba9876543210fedcba98',
    client_secret: 'not-a-real-secret',
    name: 'notebook',
    scope: 'read',
    expires_at: '2027-02-01T00:00:00Z',
    kind: 'team',
}

describe('myHoglakeCredentialsLogic', () => {
    let logic: ReturnType<typeof myHoglakeCredentialsLogic.build>
    let currentTeamId: number

    beforeEach(() => {
        initKeaTests()
        currentTeamId = teamLogic.values.currentTeamId as number
        jest.spyOn(dwApi, 'dataWarehouseMyHoglakeCredentialsRetrieve').mockResolvedValue(list(currentTeamId))
        jest.spyOn(lemonToast, 'success').mockImplementation(() => undefined as any)
        jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('loads your credentials and starts with the current project chosen', async () => {
        logic = myHoglakeCredentialsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadMyHoglakeCredentials', 'loadMyHoglakeCredentialsSuccess'])
            .toMatchValues({ effectiveTeamIds: [currentTeamId] })
    })

    it('chooses nothing when you cannot use the current project', async () => {
        jest.spyOn(dwApi, 'dataWarehouseMyHoglakeCredentialsRetrieve').mockResolvedValue({
            ...list(currentTeamId),
            projects: [{ id: OTHER_PROJECT, name: 'Staging', access: 'read' }],
        })
        logic = myHoglakeCredentialsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadMyHoglakeCredentialsSuccess']).toMatchValues({
            effectiveTeamIds: [],
        })
    })

    it('keeps only projects you can use', async () => {
        logic = myHoglakeCredentialsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadMyHoglakeCredentialsSuccess'])

        logic.actions.setSelectedTeamIds([OTHER_PROJECT, 999])

        expect(logic.values.effectiveTeamIds).toEqual([OTHER_PROJECT])
    })

    it('creates a credential for the chosen projects and holds the secret for the banner', async () => {
        const create = jest.spyOn(dwApi, 'dataWarehouseMyHoglakeCredentialsCreate').mockResolvedValue(ISSUED)
        logic = myHoglakeCredentialsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadMyHoglakeCredentialsSuccess'])

        logic.actions.createCredential({ name: 'notebook', scope: 'read', teamIds: [currentTeamId, OTHER_PROJECT] })

        await expectLogic(logic)
            .toDispatchActions(['createCredential', 'setIssuedCredential', 'submitComplete'])
            .toMatchValues({ issuedCredential: ISSUED, isSubmitting: false, newCredentialName: '' })
        expect(create).toHaveBeenCalledWith(String(currentTeamId), {
            name: 'notebook',
            scope: 'read',
            team_ids: [currentTeamId, OTHER_PROJECT],
        })
    })

    it('shows nothing when personal credentials are off', async () => {
        jest.spyOn(dwApi, 'dataWarehouseMyHoglakeCredentialsRetrieve').mockRejectedValue({ status: 501 })
        logic = myHoglakeCredentialsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadMyHoglakeCredentialsSuccess'])
            .toMatchValues({ myHoglakeCredentials: null })
    })
})
