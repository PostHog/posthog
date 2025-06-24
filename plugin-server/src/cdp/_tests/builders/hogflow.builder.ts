import { randomUUID } from 'crypto'

import { findActionByType } from '~/cdp/services/hogflows/actions/utils'
import { HogFlow, HogFlowAction, HogFlowEdge } from '~/schema/hogflow'
import { logger } from '~/utils/logger'

/**
 * Helps us build like this
    actions: {
        'action-1': {
            type: 'trigger',
            config: {
                filters: {},
            },
        },
        'action-2': {
            type: 'delay',
            config: {
                delay_duration: '1h',
            },
        },
    },
    edges: {
        'edge-1': {
            from: 'action-1',
            to: 'action-2',
            type: 'continue',
        },
        'edge-2': {
            from: 'action-2',
            to: 'action-1',
            type: 'continue',
        },
    }
 */
export type SimpleHogFlowRepresentation = {
    actions: Record<string, Pick<HogFlowAction, 'type' | 'config'> & Partial<Omit<HogFlowAction, 'type' | 'config'>>>
    edges: HogFlowEdge[]
}

export class FixtureHogFlowBuilder {
    private hogFlow: HogFlow

    constructor() {
        this.hogFlow = {
            id: randomUUID(),
            version: 1,
            name: 'Hog Flow',
            team_id: 1,
            status: 'active',
            trigger: {
                type: 'event',
                filters: {},
            },
            exit_condition: 'exit_on_conversion',
            edges: [],
            actions: [],
        }
    }

    build(): HogFlow {
        const triggerAction = findActionByType(this.hogFlow, 'trigger')
        this.hogFlow.trigger =
            this.hogFlow.trigger ??
            (triggerAction
                ? {
                      type: triggerAction?.type ?? 'event',
                      filters: triggerAction?.config?.filters ?? {},
                  }
                : undefined)

        if (!this.hogFlow.trigger) {
            logger.error('[HogFlowBuilder] No trigger action found. Indicates a faulty built workflow')
        }

        // TODO: Run throught the zod validation?

        return this.hogFlow
    }

    withName(name: string): this {
        this.hogFlow.name = name
        return this
    }

    withTeamId(teamId: number): this {
        this.hogFlow.team_id = teamId
        return this
    }

    withStatus(status: HogFlow['status']): this {
        this.hogFlow.status = status
        return this
    }

    withTrigger(trigger: HogFlow['trigger']): this {
        this.hogFlow.trigger = trigger
        return this
    }

    withExitCondition(exitCondition: HogFlow['exit_condition']): this {
        this.hogFlow.exit_condition = exitCondition
        return this
    }

    withWorkflow(workflow: SimpleHogFlowRepresentation): this {
        this.hogFlow.actions = Object.entries(workflow.actions).map(([id, action]) => ({
            id,
            name: action.type,
            description: action.type,
            created_at: Date.now(),
            updated_at: Date.now(),
            on_error: 'continue',
            ...(action as any), // TRICKY: Nasty cast as the union types are beyond me get right
        }))

        this.hogFlow.edges = workflow.edges

        return this
    }
}
