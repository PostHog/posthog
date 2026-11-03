import { Suspense, createElement } from 'react'

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

type IntegrationSetupModalProps = {
    isOpen: boolean
    kind: string
    integration?: any
    onComplete: (id?: number) => void
    onClose: () => void
}

export type IntegrationSetupDefinition = {
    kind: string | string[]
    menuItem: (ctx: IntegrationSetupContext) => IntegrationSetupMenuItem
    SetupModal?: React.ComponentType<IntegrationSetupModalProps>
}

const registeredSetups = new Map<string, IntegrationSetupDefinition>()

// Setup modals load lazily, so each one gets its own Suspense boundary instead of suspending the form around it.
function withSuspense(
    SetupModal: React.ComponentType<IntegrationSetupModalProps>
): React.ComponentType<IntegrationSetupModalProps> {
    return function SuspendedSetupModal(props) {
        return createElement(Suspense, { fallback: null }, createElement(SetupModal, props))
    }
}

export function registerIntegrationSetup(setup: IntegrationSetupDefinition): void {
    const def = setup.SetupModal ? { ...setup, SetupModal: withSuspense(setup.SetupModal) } : setup
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
