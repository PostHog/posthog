import { IngestionGeneralServer } from './ingestion-general-server'

describe('IngestionGeneralServer', () => {
    it('refuses to start with outputs disabled, since its other pipelines would still produce', () => {
        expect(() => new IngestionGeneralServer({ INGESTION_OUTPUTS_DISABLED: true })).toThrow(
            /INGESTION_OUTPUTS_DISABLED/
        )
    })
})
