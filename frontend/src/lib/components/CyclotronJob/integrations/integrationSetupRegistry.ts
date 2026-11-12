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

// Setup form values the user may not change. The form starts with them, shows them read-only, and saves them as
// they are. The modal reads them once, when it mounts.
export type LockedSetupValues = {
    values: Record<string, any>
    // Shown on each read-only field.
    reason: string
}

type IntegrationSetupModalProps = {
    isOpen: boolean
    kind: string
    integration?: any
    locked?: LockedSetupValues
    onComplete: (id?: number) => void
    onClose: () => void
}

export type IntegrationSetupDefinition = {
    kind: string | string[]
    menuItem: (ctx: IntegrationSetupContext) => IntegrationSetupMenuItem
    SetupModal?: React.ComponentType<IntegrationSetupModalProps>
    // Setup form field -> key in a migrated destination's vendor config, for the non-secret fields only.
    vendorConfigKeys?: Record<string, string>
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
