import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import * as dwApi from 'products/data_warehouse/frontend/generated/api'
import type {
    HoglakeCredentialIssuedApi,
    HoglakeCredentialListResponseApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { hoglakeCredentialsLogic } from './hoglakeCredentialsLogic'

const LIST: HoglakeCredentialListResponseApi = {
    hoglake_credentials: [
        {
            client_id: 'hlc_0123456789abcdef01234567',
            name: 'laptop',
            scope: 'read',
            created_at: '2026-11-01T00:00:00Z',
            last_rotated_at: '2026-11-01T00:00:00Z',
            expires_at: '2027-02-01T00:00:00Z',
        },
    ],
    connect: { catalog: 'org-1', token_url: 'https://hogtower-oauth.example.test/oauth/token' },
}

const ISSUED: HoglakeCredentialIssuedApi = {
    client_id: 'hlc_fedcba9876543210fedcba98',
    client_secret: 'not-a-real-secret',
    name: 'airflow',
    scope: 'write',
    expires_at: '2027-02-01T00:00:00Z',
}

describe('hoglakeCredentialsLogic', () => {
    let logic: ReturnType<typeof hoglakeCredentialsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(dwApi, 'dataWarehouseHoglakeCredentialsRetrieve').mockResolvedValue(LIST)
        jest.spyOn(lemonToast, 'success').mockImplementation(() => undefined as any)
        jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('loads the credentials on mount', async () => {
        logic = hoglakeCredentialsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadHoglakeCredentials', 'loadHoglakeCredentialsSuccess'])
            .toMatchValues({ hoglakeCredentials: LIST })
        expect(dwApi.dataWarehouseHoglakeCredentialsRetrieve).toHaveBeenCalledTimes(1)
    })

    it.each([403, 501])('treats a %s as nothing to show', async (status) => {
        jest.spyOn(dwApi, 'dataWarehouseHoglakeCredentialsRetrieve').mockRejectedValue({ status })

        logic = hoglakeCredentialsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadHoglakeCredentialsSuccess'])
            .toMatchValues({ hoglakeCredentials: null })
        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('shows the issued secret once and clears the name after create', async () => {
        const create = jest.spyOn(dwApi, 'dataWarehouseHoglakeCredentialsCreate').mockResolvedValue(ISSUED)

        logic = hoglakeCredentialsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadHoglakeCredentialsSuccess'])

        logic.actions.setNewCredentialName('airflow')
        logic.actions.createCredential({ name: 'airflow', scope: 'write' })

        await expectLogic(logic)
            .toDispatchActions(['setIssuedCredential', 'submitComplete', 'loadHoglakeCredentials'])
            .toMatchValues({ issuedCredential: ISSUED, newCredentialName: '', isSubmitting: false })
        expect(create).toHaveBeenCalledWith(expect.any(String), { name: 'airflow', scope: 'write' })

        logic.actions.setIssuedCredential(null)
        expect(logic.values.issuedCredential).toBeNull()
    })

    it('reports a failed create and keeps the name', async () => {
        jest.spyOn(dwApi, 'dataWarehouseHoglakeCredentialsCreate').mockRejectedValue({
            data: { error: 'too many live credentials' },
        })

        logic = hoglakeCredentialsLogic()
        logic.mount()
        logic.actions.setNewCredentialName('airflow')
        logic.actions.createCredential({ name: 'airflow', scope: 'read' })

        await expectLogic(logic)
            .toDispatchActions(['submitComplete'])
            .toMatchValues({ issuedCredential: null, newCredentialName: 'airflow' })
        expect(lemonToast.error).toHaveBeenCalledWith('Failed to create the credential: too many live credentials')
    })

    it('rotates into a new one-time secret and revokes by client id', async () => {
        const rotate = jest.spyOn(dwApi, 'dataWarehouseHoglakeCredentialsRotateCreate').mockResolvedValue(ISSUED)
        const revoke = jest
            .spyOn(dwApi, 'dataWarehouseHoglakeCredentialsDestroy')
            .mockResolvedValue({ revoked: ISSUED.client_id })

        logic = hoglakeCredentialsLogic()
        logic.mount()

        logic.actions.rotateCredential(ISSUED.client_id)
        await expectLogic(logic)
            .toDispatchActions(['setIssuedCredential', 'submitComplete'])
            .toMatchValues({ issuedCredential: ISSUED })
        expect(rotate).toHaveBeenCalledWith(expect.any(String), ISSUED.client_id)

        logic.actions.revokeCredential(ISSUED.client_id)
        await expectLogic(logic).toDispatchActions(['submitComplete', 'loadHoglakeCredentials'])
        expect(revoke).toHaveBeenCalledWith(expect.any(String), ISSUED.client_id)
    })
})
