import * as Sentry from '@sentry/node'
import { StatsD } from 'hot-shots'
import { Consumer } from 'kafkajs'

import { Hub } from '../../types'

type PartitionAssignment = {
    readonly topic: string
    readonly partitions: readonly number[]
}

type MemberAssignment = {
    readonly version: number
    readonly partitionAssignments: readonly PartitionAssignment[]
    readonly userData: Buffer
}

export async function emitConsumerGroupMetrics(
    consumer: Consumer,
    consumerGroupMemberId: string | null,
    pluginsServer: Hub
): Promise<void> {
    try {
        const timer = new Date()
        const description = await consumer.describeGroup()
        pluginsServer.statsd?.timing('kafka_consumer_emit_describe', timer)

        pluginsServer.statsd?.increment('kafka_consumer_group_state', {
            state: description.state,
            groupId: description.groupId,
            instanceId: pluginsServer.instanceId.toString(),
        })

        const descriptionWithAssignment = description.members.map((member) => ({
            ...member,
            assignment: parseMemberAssignment(member.memberAssignment),
        }))

        const consumerDescription = descriptionWithAssignment.find(
            (assignment) => assignment.memberId === consumerGroupMemberId
        )

        let isLive = false
        if (consumerDescription) {
            consumerDescription.assignment.partitionAssignments.forEach(({ topic, partitions }) => {
                isLive = isLive || partitions.length > 0
                pluginsServer.statsd?.gauge('kafka_consumer_group_assigned_partitions', partitions.length, {
                    topic,
                    memberId: consumerGroupMemberId || 'unknown',
                    groupId: description.groupId,
                    instanceId: pluginsServer.instanceId.toString(),
                })
            })
        }

        pluginsServer.statsd?.increment(isLive ? 'kafka_consumer_live' : 'kafka_consumer_group_idle', {
            memberId: consumerGroupMemberId || 'unknown',
            groupId: description.groupId,
            instanceId: pluginsServer.instanceId.toString(),
        })
    } catch (error) {
        pluginsServer.statsd?.increment('kafka_consumer_emit_describe_failure', {
            memberId: consumerGroupMemberId || 'unknown',
            instanceId: pluginsServer.instanceId.toString(),
        })

        Sentry.captureException(error)
    }
}

export function addMetricsEventListeners(consumer: Consumer, statsd: StatsD | undefined): void {
    const listenEvents = [
        consumer.events.GROUP_JOIN,
        consumer.events.CONNECT,
        consumer.events.DISCONNECT,
        consumer.events.STOP,
        consumer.events.CRASH,
        consumer.events.RECEIVED_UNSUBSCRIBED_TOPICS,
        consumer.events.REQUEST_TIMEOUT,
    ]

    listenEvents.forEach((event) => {
        consumer.on(event, () => {
            statsd?.increment('kafka_queue_consumer_event', { event })
        })
    })
}

// Lifted from https://github.com/tulios/kafkajs/issues/755
const parseMemberAssignment = (data: Buffer): MemberAssignment => {
    let currentOffset = 0

    const version = data.readInt16BE(currentOffset)

    currentOffset += 2

    const partitionAssignmentCount = data.readInt32BE(currentOffset)

    currentOffset += 4

    const partitionAssignments = []

    for (let n = 0; n < partitionAssignmentCount; n += 1) {
        const topicNameLength = data.readInt16BE(currentOffset)

        currentOffset += 2

        const topic = data.slice(currentOffset, currentOffset + topicNameLength).toString('utf-8')

        currentOffset += topicNameLength

        const partitionCount = data.readInt32BE(currentOffset)

        currentOffset += 4

        const partitions = []

        for (let n2 = 0; n2 < partitionCount; n2 += 1) {
            const partition = data.readInt32BE(currentOffset)

            currentOffset += 4

            partitions.push(partition)
        }

        const partitionAssignment = { topic, partitions } as const

        partitionAssignments.push(partitionAssignment)
    }

    const userData = data.slice(currentOffset)

    const memberAssignment = { version, partitionAssignments, userData } as const

    return memberAssignment
}
