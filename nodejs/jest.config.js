const config = require('./jest.config.shared')

module.exports = {
    ...config,
    testMatch: ['<rootDir>/tests/**/!(*.serial).test.ts', '<rootDir>/src/**/!(*.serial).test.ts'],
    // Only applies to `test.concurrent` bodies (the ingestion e2e harness). Those spend most of
    // their time waiting on ClickHouse's Kafka engine flush, so overlapping more of them per
    // worker shortens the file far more than it costs in CPU. Jest's default is 5.
    maxConcurrency: 15,
}
