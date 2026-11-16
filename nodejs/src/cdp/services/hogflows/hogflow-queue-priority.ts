export const HOGFLOW_QUEUE_PRIORITY = {
    triggered: 1,
    background: 2,
} as const

export type HogFlowQueuePriority = (typeof HOGFLOW_QUEUE_PRIORITY)[keyof typeof HOGFLOW_QUEUE_PRIORITY]

export function broadcastChildQueuePriority(lowPriority: boolean): HogFlowQueuePriority {
    return lowPriority ? HOGFLOW_QUEUE_PRIORITY.background : HOGFLOW_QUEUE_PRIORITY.triggered
}
