import { DateTime } from 'luxon'

import {
    DWH_SOURCE_TABLE_PROPERTY,
    GITHUB_EVENT_RECEIVED_EVENT,
    HogFlowAction,
    SLACK_MESSAGE_RECEIVED_EVENT,
    getInternalEventFilterEventIds,
    isRowScopedTrigger,
    rowScopedTriggerTypeForEvent,
} from '~/cdp/schema/hogflow'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'

import { findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

// The slice of IntegrationManagerService the own-app check needs, so this handler and its tests
// don't depend on the concrete Postgres-backed service. getMany has no team scoping of its own
// (it's a raw lookup by id, see IntegrationManagerService.fetchIntegrations), so team_id travels
// with the result and every caller must check it - the same contract hog-inputs.service.ts uses.
export interface SlackAppLookup {
    getMany(
        integrationIds: number[]
    ): Promise<Record<number, { team_id: number; config?: { app_id?: string | null } } | null>>
}

// NOTE: This is not an actively used action as the triggering is done by the scheduler
// but useful for testing the hogflow executor
export class TriggerHandler implements ActionHandler {
    constructor(private integrationManager: SlackAppLookup) {}

    async execute({
        invocation,
        action,
        result,
    }: ActionHandlerOptions<Extract<HogFlowAction, { type: 'trigger' }>>): Promise<ActionHandlerResult> {
        const trigger = action.config
        const event = invocation.state.event

        if (trigger.type === 'internal-event') {
            // Test runs accept arbitrary globals, so mirror the eligibility checks the
            // internal-events consumer applies before a real invocation is ever created: the
            // trigger only fires on the internal events its filters name.
            const eventIds = getInternalEventFilterEventIds(trigger.filters)
            if (!eventIds) {
                result.logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message:
                        "This trigger's filters do not name any internal events, so no event would trigger this workflow.",
                })
                return { finished: true, skipped: true }
            }
            if (!event?.event || !eventIds.includes(event.event)) {
                result.logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message: `This workflow triggers on '${eventIds.join("', '")}' events. A '${event?.event}' event would not trigger this workflow.`,
                })
                return { finished: true, skipped: true }
            }

            // Mirrors the consumer's own-app exclusion: a message PostHog's own connected Slack
            // app posted never reaches a real invocation, so a workflow can't retrigger itself
            // off its own reply. Without this, a hand-written payload naming that app passes.
            if (
                event.event === SLACK_MESSAGE_RECEIVED_EVENT &&
                (await this.isOwnSlackMessage(event.properties, invocation.teamId))
            ) {
                result.logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message: "Messages PostHog's own connected Slack app posted would not trigger this workflow.",
                })
                return { finished: true, skipped: true }
            }

            // The GitHub equivalent, resolved from the own_app property the emit stamps on the
            // event (see isOwnGithubEvent in the internal-events consumer).
            if (event.event === GITHUB_EVENT_RECEIVED_EVENT && event.properties?.own_app === true) {
                result.logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message: "Activity from PostHog's own GitHub App would not trigger this workflow.",
                })
                return { finished: true, skipped: true }
            }
        }

        // Mirrors the warehouse-events consumer's eligibility check: a warehouse-row trigger only
        // fires on a row of its own kind (source table vs materialized view) from its own table.
        // Without this, any event - a $pageview included - passes a warehouse trigger whose
        // filters are empty, which is the default for a freshly created one. isRowScopedTrigger
        // also covers internal-event, which has no table_name to check here and is handled by
        // its own eligibility checks above.
        if (trigger.type === 'data-warehouse-table' || trigger.type === 'data-warehouse-view') {
            const sourceTable = event?.properties?.[DWH_SOURCE_TABLE_PROPERTY]
            const rowTriggerType = rowScopedTriggerTypeForEvent(event?.event)
            if (rowTriggerType !== trigger.type || sourceTable !== trigger.table_name) {
                result.logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message: `This workflow triggers on rows from '${trigger.table_name}'. A '${event?.event}' event with source table '${sourceTable ?? 'none'}' would not trigger it.`,
                })
                return { finished: true, skipped: true }
            }
        }

        // The filter-carrying trigger types, the same set buildHogFlowInvocations evaluates before
        // creating a real invocation. The remaining types (webhook, manual, schedule, batch,
        // tracking_pixel) carry no event filters, so they continue unconditionally.
        if (trigger.type !== 'event' && !isRowScopedTrigger(trigger)) {
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

    private async isOwnSlackMessage(properties: Record<string, any> | undefined, teamId: number): Promise<boolean> {
        const integrationId = properties?.integration_id
        const appId = properties?.app_id
        if (typeof integrationId !== 'number' || typeof appId !== 'string') {
            return false
        }
        const integrations = await this.integrationManager.getMany([integrationId])
        const integration = integrations[integrationId]
        // integration_id and app_id come from an untrusted test-run payload, and getMany can
        // resolve an id belonging to any team - never trust its config without checking team_id
        // first, or a test run becomes a cross-team oracle for another team's Slack app_id.
        return integration?.team_id === teamId && integration?.config?.app_id === appId
    }
}
