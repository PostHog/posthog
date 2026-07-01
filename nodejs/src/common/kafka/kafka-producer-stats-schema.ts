import { z } from 'zod'

/**
 * Zod schema for the subset of the librdkafka stats JSON we consume.
 *
 * See the source-of-truth schema at
 * https://github.com/confluentinc/librdkafka/blob/master/STATISTICS.md — no
 * upstream ships a typed definition. Every field is optional because
 * librdkafka's payload varies by version, producer vs consumer, and whether
 * a given broker/topic has been interacted with yet. Unknown fields are
 * stripped (zod's default object behavior) so new additions upstream don't
 * break the parse.
 */

const brokerStatsSchema = z.object({
    state: z.string().optional(),
})

const topicStatsSchema = z.object({
    batchsize: z.object({ avg: z.number().optional() }).optional(),
    batchcnt: z.object({ avg: z.number().optional() }).optional(),
})

export const producerStatsSchema = z.object({
    msg_cnt: z.number().optional(),
    msg_size: z.number().optional(),
    msg_max: z.number().optional(),
    msg_size_max: z.number().optional(),
    replyq: z.number().optional(),
    brokers: z.record(z.string(), brokerStatsSchema).optional(),
    topics: z.record(z.string(), topicStatsSchema).optional(),
})

export type ProducerStats = z.infer<typeof producerStatsSchema>
export type BrokerStats = z.infer<typeof brokerStatsSchema>
export type TopicStats = z.infer<typeof topicStatsSchema>
