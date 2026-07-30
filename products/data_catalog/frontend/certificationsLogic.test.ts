import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { certificationsLogic } from './certificationsLogic'
import {
    dataCatalogCertificationsCertifyCreate,
    dataCatalogCertificationsDestroy,
    dataCatalogCertificationsList,
} from './generated/api'
import type { DataCatalogCertificationApi } from './generated/api.schemas'

jest.mock('lib/api', () => {
    class ApiError extends Error {
        status?: number
        detail: string | null
        constructor(message?: string, status?: number, _headers?: unknown, data?: { detail?: string }) {
            super(message)
            this.status = status
            this.detail = data?.detail ?? null
        }
    }
    return {
        __esModule: true,
        default: {},
        ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
        ApiError,
    }
})

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() },
}))

jest.mock('scenes/data-management/database/databaseTableListLogic', () => ({
    databaseTableListLogic: { loadDatabase: jest.fn(() => ({ type: 'load database (mock)' })) },
}))

jest.mock('./generated/api', () => ({
    dataCatalogCertificationsList: jest.fn(),
    dataCatalogCertificationsCreate: jest.fn(),
    dataCatalogCertificationsCertifyCreate: jest.fn(),
    dataCatalogCertificationsDeprecateCreate: jest.fn(),
    dataCatalogCertificationsDestroy: jest.fn(),
}))

// The whole logic module is mocked above; loadDatabase is a jest.fn at runtime.
const mockLoadDatabase = (databaseTableListLogic as unknown as { loadDatabase: jest.Mock }).loadDatabase

function buildCertification(overrides: Partial<DataCatalogCertificationApi>): DataCatalogCertificationApi {
    return {
        id: 'cert-1',
        target_name: 'stripe_charges',
        target_type: 'table',
        status: 'proposed',
        notes: '',
        ...overrides,
    } as DataCatalogCertificationApi
}

describe('certificationsLogic', () => {
    let logic: ReturnType<typeof certificationsLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        ;(dataCatalogCertificationsList as jest.Mock).mockResolvedValue({
            results: [
                buildCertification({ id: 'cert-1', status: 'proposed' }),
                buildCertification({ id: 'cert-2', status: 'certified' }),
            ],
        })
        initKeaTests()
        logic = certificationsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCertificationsSuccess'])
    })

    it('counts only proposed certifications as pending', () => {
        expect(logic.values.proposedCount).toEqual(1)
    })

    it('replaces the row status from the response when certifying', async () => {
        ;(dataCatalogCertificationsCertifyCreate as jest.Mock).mockResolvedValue(
            buildCertification({ id: 'cert-1', status: 'certified' })
        )

        logic.actions.certifyCertification('cert-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.certifications.find((certification) => certification.id === 'cert-1')?.status).toEqual(
            'certified'
        )
        // Badges elsewhere read certification state off the shared schema, so it must be refreshed.
        expect(mockLoadDatabase).toHaveBeenCalledWith({ force: true })
    })

    it('removes the row when revoking', async () => {
        ;(dataCatalogCertificationsDestroy as jest.Mock).mockResolvedValue(undefined)

        logic.actions.revokeCertification('cert-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.certifications.map((certification) => certification.id)).not.toContain('cert-1')
        // Badges elsewhere read certification state off the shared schema, so it must be refreshed.
        expect(mockLoadDatabase).toHaveBeenCalledWith({ force: true })
    })
})
