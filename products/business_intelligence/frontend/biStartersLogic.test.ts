import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { biStartersLogic } from './biStartersLogic'

it('requests one bounded, server-filtered page of certified sources', async () => {
    initKeaTests()
    let certificationParams: Record<string, string> = {}
    const certifications = jest.fn(({ request }: { request: Request }) => {
        certificationParams = Object.fromEntries(new URL(request.url).searchParams)
        return { results: [], next: 'next-page' }
    })
    useMocks({
        get: {
            '/api/projects/:team_id/data_catalog/certifications/': certifications,
        },
    })
    const logic = biStartersLogic()
    const unmount = logic.mount()
    try {
        await expectLogic(logic).toFinishAllListeners()
        expect(certifications).toHaveBeenCalledTimes(1)
        expect(certificationParams).toEqual({ status: 'certified', limit: '3' })
    } finally {
        unmount()
    }
})

it('keeps the library usable when optional catalog endpoints are unavailable', async () => {
    initKeaTests()
    useMocks({
        get: {
            '/api/projects/:team_id/data_catalog/certifications/': [403, { detail: 'Unavailable' }],
        },
    })
    const logic = biStartersLogic()
    const unmount = logic.mount()
    try {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.sources).toEqual([])
        expect(logic.values.sourcesLoading).toBe(false)
    } finally {
        unmount()
    }
})
