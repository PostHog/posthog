import { createEventUsageBatchFactory } from './index'

describe('createEventUsageBatchFactory', () => {
    const config = {
        USAGE_INGESTION_ADDR: 'localhost:7143',
        USAGE_INGESTION_TLS: false,
        USAGE_INGESTION_TIMEOUT_MS: 5_000,
        USAGE_INGESTION_MAX_BATCH_SIZE: 500,
        USAGE_INGESTION_REPORT_TEAMS: '2,4',
    }

    // A batch that accepts nothing reports nothing, and that silence reads the same as a
    // working collector with no traffic. Both halves of the config have to reach the batch,
    // or a deployment looks enabled and bills nobody.
    it.each([
        ['bills a listed team when the address and the team list are both set', config, true],
        ['bills nothing when the address is empty', { ...config, USAGE_INGESTION_ADDR: '' }, false],
        ['bills nothing when the team list is empty', { ...config, USAGE_INGESTION_REPORT_TEAMS: '' }, false],
        ['bills nothing for a team outside the list', { ...config, USAGE_INGESTION_REPORT_TEAMS: '4' }, false],
    ])('%s', (_name, usageConfig, billed) => {
        expect(createEventUsageBatchFactory(usageConfig, 'events')().accepts(2)).toBe(billed)
    })
})
