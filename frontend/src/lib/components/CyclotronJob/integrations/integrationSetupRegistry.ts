import { IntegrationKind } from '~/types'

export type IntegrationSetupMenuItem = {
    label: string
    onClick?: () => void
    to?: string
    disableClientSideRouting?: boolean
}

export type IntegrationSetupContext = {
    kind: string
    openModal: (kind: IntegrationKind) => void
    uploadKey: (kind: string) => void
}

export type IntegrationSetupDefinition = {
    kind: string | string[]
    menuItem: (ctx: IntegrationSetupContext) => IntegrationSetupMenuItem
    SetupModal?: React.ComponentType<{
        isOpen: boolean
        kind: string
        integration?: any
        onComplete: (id?: number) => void
        onClose: () => void
    }>
}

const registeredSetups = new Map<string, IntegrationSetupDefinition>()

export function registerIntegrationSetup(def: IntegrationSetupDefinition): void {
    const kinds = Array.isArray(def.kind) ? def.kind : [def.kind]
    for (const k of kinds) {
        registeredSetups.set(k, def)
    }
}

export function getIntegrationSetup(kind: string): IntegrationSetupDefinition | undefined {
    return registeredSetups.get(kind)
}

export function getAllRegisteredIntegrationSetups(): IntegrationSetupDefinition[] {
    return [...new Set(registeredSetups.values())]
}
