import { Message, MessageHeader } from 'node-rdkafka'
import { z } from 'zod'

import { KafkaConsumerBreadcrumb, KafkaConsumerBreadcrumbSchema } from '../../types'
import { parseJSON } from '../../utils/json-parse'

export function createBreadcrumb(message: Message, consumerGroupId: string): KafkaConsumerBreadcrumb {
    return {
        topic: message.topic,
        partition: message.partition,
        offset: message.offset,
        processed_at: new Date().toISOString(),
        consumer_id: consumerGroupId,
    }
}

export function getExistingBreadcrumbsFromHeaders(message: Message): KafkaConsumerBreadcrumb[] {
    const existingBreadcrumbs: KafkaConsumerBreadcrumb[] = []
    if (message.headers) {
        for (const header of message.headers) {
            if ('kafka-consumer-breadcrumbs' in header) {
                try {
                    const headerValue = header['kafka-consumer-breadcrumbs']
                    const valueString = headerValue instanceof Buffer ? headerValue.toString() : String(headerValue)
                    const parsedValue = parseJSON(valueString)
                    if (Array.isArray(parsedValue)) {
                        const validatedBreadcrumbs = z.array(KafkaConsumerBreadcrumbSchema).safeParse(parsedValue)
                        if (validatedBreadcrumbs.success) {
                            existingBreadcrumbs.push(...validatedBreadcrumbs.data)
                        }
                    } else {
                        const validatedBreadcrumb = KafkaConsumerBreadcrumbSchema.safeParse(parsedValue)
                        if (validatedBreadcrumb.success) {
                            existingBreadcrumbs.push(validatedBreadcrumb.data)
                        }
                    }
                } catch (e) {
                    // Ignore parsing errors
                }
            }
        }
    }
    return existingBreadcrumbs
}

export function addBreadcrumbsToHeaders(message: Message, consumerGroupId: string): MessageHeader[] {
    const existingBreadcrumbs = getExistingBreadcrumbsFromHeaders(message)
    const breadcrumb = createBreadcrumb(message, consumerGroupId)
    const allBreadcrumbs = [...existingBreadcrumbs, breadcrumb]

    const headers: MessageHeader[] = message.headers ?? []
    headers.push({
        'kafka-consumer-breadcrumbs': Buffer.from(JSON.stringify(allBreadcrumbs)),
    })
    return headers
}
