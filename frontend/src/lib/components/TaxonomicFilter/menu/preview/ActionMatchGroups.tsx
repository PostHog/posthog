/**
 * Action match-groups list for the preview pane. Renders
 * `MATCH GROUP N: <event>` cards joined by "OR" separators. Direct
 * Quill-styled port of the legacy `ActionPopoverInfo` so we don't pull
 * in the kea-coupled `DefinitionPopover` primitives.
 */
import { Separator } from '@posthog/quill'

import { genericOperatorToHumanName, propertyValueToHumanName } from 'lib/components/DefinitionPopover/utils'

import { ActionStepType, ActionType } from '~/types'

import { TaxonomicDefinitionTypes } from '../../types'

export function ActionMatchGroups({ item }: { item: TaxonomicDefinitionTypes }): JSX.Element | null {
    const action = item as ActionType
    if (!action || !Array.isArray(action.steps) || action.steps.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-3 border-t pt-2">
            {action.steps.map((step, idx) => (
                <div key={idx} className="flex flex-col gap-2">
                    <MatchGroup index={idx + 1} step={step} />
                    {idx < action.steps!.length - 1 && (
                        <div className="flex items-center gap-2 text-xxs uppercase tracking-wide text-secondary">
                            <Separator className="flex-1" />
                            <span>OR</span>
                            <Separator className="flex-1" />
                        </div>
                    )}
                </div>
            ))}
        </div>
    )
}

function MatchGroup({ index, step }: { index: number; step: ActionStepType }): JSX.Element {
    const conditions: JSX.Element[] = []
    if (step.selector) {
        conditions.push(
            <li key="sel">
                Element matches CSS selector <Mono>{step.selector}</Mono>
            </li>
        )
    }
    if (step.text) {
        conditions.push(
            <li key="text">
                Text{' '}
                {step.text_matching === 'regex'
                    ? 'matches regex'
                    : step.text_matching === 'exact'
                      ? 'equals'
                      : 'contains'}{' '}
                <Mono>{step.text}</Mono>
            </li>
        )
    }
    if (step.href) {
        conditions.push(
            <li key="href">
                Href{' '}
                {step.href_matching === 'regex'
                    ? 'matches regex'
                    : step.href_matching === 'exact'
                      ? 'equals'
                      : 'contains'}{' '}
                <Mono>{step.href}</Mono>
            </li>
        )
    }
    if (step.url) {
        conditions.push(
            <li key="url">
                URL{' '}
                {step.url_matching === 'regex'
                    ? 'matches regex'
                    : step.url_matching === 'exact'
                      ? 'equals'
                      : 'contains'}{' '}
                <Mono>{step.url}</Mono>
            </li>
        )
    }
    step.properties?.forEach((p, pi) => {
        conditions.push(
            <li key={`p-${pi}`}>
                <Mono>{p.key}</Mono> {genericOperatorToHumanName(p)} <Mono>{propertyValueToHumanName(p.value)}</Mono>
            </li>
        )
    })
    return (
        <div className="flex flex-col gap-1">
            <div className="text-xxs uppercase tracking-wide text-secondary">
                Match group {index}: <span className="font-mono normal-case text-foreground">{step.event ?? '—'}</span>
            </div>
            {conditions.length > 0 && (
                <ul className="text-xs text-secondary list-disc pl-4 space-y-0.5">{conditions}</ul>
            )}
        </div>
    )
}

function Mono({ children }: { children: React.ReactNode }): JSX.Element {
    return <span className="font-mono text-foreground">{children}</span>
}
