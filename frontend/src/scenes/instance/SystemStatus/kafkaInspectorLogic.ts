import { actions, kea, path } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { kafkaInspectorLogicType } from './kafkaInspectorLogicType'
export interface KafkaMessage {
    topic: string
    partition: number
    offset: number
    timestamp: number
    key: string
    value: Record<string, any> | string
}

export const kafkaInspectorLogic = kea<kafkaInspectorLogicType>([
    path(['scenes', 'instance', 'SystemStatus', 'kafkaInspectorLogic']),
    actions({
        fetchKafkaMessage: (topic: string, partition: number, offset: number) => ({ topic, partition, offset }),
    }),
    loaders({
        kafkaMessage: [
            null as KafkaMessage | null,
            {
                fetchKafkaMessage: async ({ topic, partition, offset }) => {
                    return await api.create('api/kafka_inspector/fetch_message', { topic, partition, offset })
                },
            },
        ],
    }),
    forms(({ actions }) => ({
        fetchKafkaMessage: {
            defaults: { topic: 'clickhouse_events_json', partition: 0, offset: 0 },
            submit: ({ topic, partition, offset }: { topic: string; partition: number; offset: number }) => {
                actions.fetchKafkaMessage(topic, Number(partition), Number(offset))
            },
        },
    })),
])
