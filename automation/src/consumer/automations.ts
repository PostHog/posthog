import { postgresQuery } from '../utils/postgres'
import { AutomationType, EventType } from '../types'

export class Automations {
    private static _cachedAutomations: Promise<Automation[]> | null = null

    static async automations(): Promise<Automation[]> {
        if (!Automations._cachedAutomations) {
            Automations._cachedAutomations = Automations.loadAll()
        }

        return Automations._cachedAutomations
    }

    static async loadAll(): Promise<Automation[]> {
        const result = await postgresQuery('SELECT * FROM posthog_automations', [], 'fetchAllAutomations')

        // TODO: This isn't right
        return result as unknown as Automation[]
    }
}

export class Automation {
    constructor(private automation: AutomationType) {}

    checkEvent(event: EventType): boolean {
        return true
    }
}
