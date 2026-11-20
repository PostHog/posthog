import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'

// An events goal with no event means "All events", which marketing analytics cannot attribute.
export function isInvalidConversionGoal(goal: ConversionGoalFilter): boolean {
    return (
        goal.kind === NodeKind.EventsNode &&
        ('event' in goal ? (goal as any).event === null || (goal as any).event === '' : false)
    )
}
