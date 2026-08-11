import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { certificationsLogic } from './certificationsLogic'
import type { CertificationsFilters } from './certificationsLogic'
import {
    dataCatalogCertificationsCertifyCreate,
    dataCatalogCertificationsCreate,
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

    it.each<[Partial<CertificationsFilters>, string[]]>([
        [{ status: 'proposed' }, ['cert-1', 'cert-4']],
        [{ status: 'certified' }, ['cert-2']],
        [{ search: 'invoices' }, ['cert-2']],
        [{ status: 'proposed', search: 'legacy' }, ['cert-4']],
    ])('narrows filteredCertifications with filters %o', (filters, expectedIds) => {
        logic.actions.loadCertificationsSuccess([
            buildCertification({ id: 'cert-1', status: 'proposed', target_name: 'stripe_charges' }),
            buildCertification({ id: 'cert-2', status: 'certified', target_name: 'stripe_invoices' }),
            buildCertification({ id: 'cert-3', status: 'deprecated', target_name: 'old_revenue' }),
            // A proposed deprecation keeps raw status "proposed", so it must land under the Proposed filter.
            buildCertification({
                id: 'cert-4',
                status: 'proposed',
                proposed_status: 'deprecated',
                target_name: 'legacy_events',
            }),
        ])
        logic.actions.setFilters(filters)

        expect(logic.values.filteredCertifications.map((certification) => certification.id)).toEqual(expectedIds)
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

    it('sends the proposal intent when creating', async () => {
        ;(dataCatalogCertificationsCreate as jest.Mock).mockResolvedValue(
            buildCertification({ id: 'cert-3', status: 'proposed' })
        )

        logic.actions.setNewCertificationForm({ targetName: 'stale_revenue', proposedStatus: 'deprecated' })
        logic.actions.createCertification()
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogCertificationsCreate).toHaveBeenCalledWith('1', {
            table_name: 'stale_revenue',
            notes: undefined,
            proposed_status: 'deprecated',
        })
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
