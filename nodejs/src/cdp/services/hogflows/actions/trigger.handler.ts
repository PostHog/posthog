import { DateTime } from 'luxon'

import {
    DWH_SOURCE_TABLE_PROPERTY,
    HogFlowAction,
    SLACK_MESSAGE_RECEIVED_EVENT,
    isRowScopedTrigger,
    rowScopedTriggerTypeForEvent,
} from '~/cdp/schema/hogflow'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'

import { findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

// NOTE: This is not an actively used action as the triggering is done by the scheduler
// but useful for testing the hogflow executor
export class TriggerHandler implements ActionHandler {
    async execute({
        invocation,
        action,
        result,
    }: ActionHandlerOptions<Extract<HogFlowAction, { type: 'trigger' }>>): Promise<ActionHandlerResult> {
        const trigger = action.config
        const event = invocation.state.event

        // Test runs accept arbitrary globals, so mirror the eligibility check the internal-events
        // consumer applies before a real invocation is ever created: a slack-message trigger only
        // fires on $slack_message_received events.
        if (trigger.type === 'slack-message' && event?.event !== SLACK_MESSAGE_RECEIVED_EVENT) {
            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: `Slack message triggers only fire for '${SLACK_MESSAGE_RECEIVED_EVENT}' events. A '${event?.event}' event would not trigger this workflow.`,
            })
            return { finished: true, skipped: true }
        }

        // Mirrors the warehouse-events consumer's eligibility check: a row-scoped trigger only
        // fires on a row of its own kind (source table vs materialized view) from its own table.
        // Without this, any event - a $pageview included - passes a row-scoped trigger whose
        // filters are empty, which is the default for a freshly created one.
        if (isRowScopedTrigger(trigger)) {
            const sourceTable = event?.properties?.[DWH_SOURCE_TABLE_PROPERTY]
            const rowTriggerType = rowScopedTriggerTypeForEvent(event?.event)
            if (rowTriggerType !== trigger.type || sourceTable !== trigger.table_name) {
                result.logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message: `This workflow triggers on rows from '${trigger.table_name}'. A '${event?.event}' event with source table '${sourceTable}' would not trigger it.`,
                })
                return { finished: true, skipped: true }
            }
        }

        // The filter-carrying trigger types, the same set buildHogFlowInvocations evaluates before
        // creating a real invocation. The remaining types (webhook, manual, schedule, batch,
        // tracking_pixel) carry no event filters, so they continue unconditionally.
        if (trigger.type !== 'event' && trigger.type !== 'slack-message' && !isRowScopedTrigger(trigger)) {
            return { nextAction: findContinueAction(invocation) }
        }

        const filterResults = await filterFunctionInstrumented({
            fn: invocation.hogFlow,
            filters: trigger.filters,
            filterGlobals: invocation.filterGlobals,
        })

        if (filterResults.error) {
            throw new Error(filterResults.error as string)
        }

        if (!filterResults.match) {
            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: 'Workflow trigger did not match the event.',
            })
            return { finished: true, skipped: true }
        }

        return { nextAction: findContinueAction(invocation) }
    }
}
