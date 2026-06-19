import clsx from 'clsx'

import { LemonModal } from '@posthog/lemon-ui'

import { ONBOARDING_ROLES, type OnboardingRole } from '../data/roles'

function RoleCard({
    role,
    selected,
    onClick,
}: {
    role: OnboardingRole
    selected: boolean
    onClick: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'flex flex-col overflow-hidden rounded-lg border bg-surface-primary text-left transition-colors',
                selected ? 'border-accent' : 'border-primary hover:border-accent'
            )}
        >
            <div className="flex h-28 items-end justify-center bg-surface-secondary">
                <role.Hog className="h-24 w-auto" />
            </div>
            <div className="border-t border-primary p-3">
                <div className="font-semibold text-default">{role.label}</div>
                <div className="text-secondary mt-1 text-xs leading-snug">{role.blurb}</div>
            </div>
        </button>
    )
}

/** Modal of hedgehog "character" cards for picking a role on the create-organization step. */
export function RoleSelectModal({
    isOpen,
    selectedRoleId,
    onSelect,
    onClose,
}: {
    isOpen: boolean
    selectedRoleId: string | null
    onSelect: (roleId: string) => void
    onClose: () => void
}): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="What best describes you?"
            description="So we surface the metrics and first actions that matter to you."
            width={760}
        >
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {ONBOARDING_ROLES.map((role) => (
                    <RoleCard
                        key={role.id}
                        role={role}
                        selected={role.id === selectedRoleId}
                        onClick={() => onSelect(role.id)}
                    />
                ))}
            </div>
        </LemonModal>
    )
}
