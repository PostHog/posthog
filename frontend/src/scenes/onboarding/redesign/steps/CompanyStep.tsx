import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'

import { COMPANY_ARCHETYPES, type CompanyArchetype } from '../data/archetypes'
import { onboardingLogic } from '../onboardingLogic'

function ArchetypeCard({
    archetype,
    selected,
    onClick,
}: {
    archetype: CompanyArchetype
    selected: boolean
    onClick: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'relative flex flex-col gap-3 rounded-lg border bg-surface-primary p-4 text-left transition-colors',
                selected ? 'border-accent' : 'border-primary hover:border-accent'
            )}
        >
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-secondary">
                <archetype.Icon color={archetype.color} className="text-xl" />
            </span>
            <div>
                <div className="font-semibold text-default">{archetype.label}</div>
                <div className="text-secondary mt-1 text-sm leading-snug">{archetype.description}</div>
            </div>
            {selected && <IconCheck className="text-accent absolute right-3 top-3 text-lg" />}
        </button>
    )
}

/** Step 1: pick a company archetype, which seeds the recommended products. */
export function CompanyStep(): JSX.Element {
    const { organizationName, archetypeId } = useValues(onboardingLogic)
    const { setArchetype } = useActions(onboardingLogic)
    const orgName = organizationName.trim() || 'your company'

    return (
        <div className="max-w-xl">
            <h1 className="text-3xl font-bold text-default">What is {orgName} building?</h1>
            <p className="text-secondary mt-2">
                We'll tailor your dashboards, products and first actions to what you're building.
            </p>
            <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
                {COMPANY_ARCHETYPES.map((archetype) => (
                    <ArchetypeCard
                        key={archetype.id}
                        archetype={archetype}
                        selected={archetypeId === archetype.id}
                        onClick={() => setArchetype(archetypeId === archetype.id ? null : archetype.id)}
                    />
                ))}
            </div>
        </div>
    )
}
