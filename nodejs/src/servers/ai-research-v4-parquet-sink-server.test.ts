import { KAFKA_AI_RESEARCH_V4_INDEX } from '~/common/config/kafka-topics'
import { buildAiResearchV4ServerConfig } from '~/ingestion/pipelines/sessionreplay/ai-research/config'

import { buildV4SinkConsumerConfig } from './ai-research-v4-parquet-sink-server'

describe('v4 Parquet sink wiring', () => {
    it('reads the v4 index topic in its own group, storing offsets only after a flush', () => {
        const config = buildV4SinkConsumerConfig(buildAiResearchV4ServerConfig({}))
        expect(config).toMatchObject({
            topic: KAFKA_AI_RESEARCH_V4_INDEX,
            groupId: 'ai-research-v4-parquet-sink',
            autoCommit: true,
            autoOffsetStore: false,
            callEachBatchWhenEmpty: true,
        })
    })

    it.each(['', 'session-replay-ml-parquet-sink'])('refuses the group %p', (group) => {
        const config = buildAiResearchV4ServerConfig({ AI_RESEARCH_V4_PARQUET_SINK_GROUP_ID: group })
        expect(() => buildV4SinkConsumerConfig(config)).toThrow('AI_RESEARCH_V4_PARQUET_SINK_GROUP_ID')
    })
})
