import { defaultConfig } from '~/common/config/config'
import { getDefaultIngestionConsumerConfig, getDefaultIngestionOutputsConfig } from '~/ingestion/config'

import { BatchWritingPersonsStore } from './batch-writing-person-store'
import { PersonsStoreConfig, buildPersonsStore } from './persons-store-factory'
import { RoutingPersonsStore } from './routing-persons-store'

describe('buildPersonsStore', () => {
    const config: PersonsStoreConfig = {
        ...defaultConfig,
        ...getDefaultIngestionConsumerConfig(),
        ...getDefaultIngestionOutputsConfig(),
    }
    const personRepository = {} as never
    const outputs = {} as never

    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('pg mode builds the Postgres store alone', async () => {
        const built = buildPersonsStore({ ...config, PERSONS_STORE_MODE: 'pg' }, personRepository, outputs)

        expect(built.personsStore).toBeInstanceOf(BatchWritingPersonsStore)
        await built.personsStore.shutdown()
        built.close()
        expect(jest.getTimerCount()).toBe(0)
    })

    it.each(['shadow', 'personhog'] as const)(
        '%s mode routes through personhog, and shutdown plus close() leaves no session poller to keep the process alive',
        async (mode) => {
            const built = buildPersonsStore(
                {
                    ...config,
                    PERSONS_STORE_MODE: mode,
                    PERSONHOG_ADDR: 'router.invalid:1',
                    PERSONHOG_IDENTITY_ADDR: 'identity.invalid:1',
                },
                personRepository,
                outputs
            )

            expect(built.personsStore).toBeInstanceOf(RoutingPersonsStore)
            await built.personsStore.shutdown()
            expect(jest.getTimerCount()).toBeGreaterThan(0)
            built.close()
            expect(jest.getTimerCount()).toBe(0)
        }
    )

    it('a non-pg mode without its endpoints fails at build time', () => {
        expect(() =>
            buildPersonsStore(
                { ...config, PERSONS_STORE_MODE: 'shadow', PERSONHOG_ADDR: '', PERSONHOG_IDENTITY_ADDR: '' },
                personRepository,
                outputs
            )
        ).toThrow('PERSONHOG_ADDR and PERSONHOG_IDENTITY_ADDR')
    })
})
