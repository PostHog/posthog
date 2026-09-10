import { genericOperatorToHumanName, propertyValueToHumanName } from 'lib/components/DefinitionPopover/utils'
import { stripHTTP } from 'lib/utils/url'

import { ActionStepType } from '~/types'

import { SCREEN_NAME_MATCHING_LABEL, type ScreenNameMatching, isScreenNameFilter } from './screenName'

const MAX_INLINE_LENGTH = 40

function truncate(value: string): string {
    return value.length > MAX_INLINE_LENGTH ? value.slice(0, MAX_INLINE_LENGTH) + '…' : value
}

function stringMatchingVerb(matching?: string | null): string {
    return matching === 'regex' ? 'matches regex' : matching === 'exact' ? 'equals' : 'contains'
}

/** The single most recognizable detail of an autocapture step: its text, else selector, else link. */
function autocaptureIdentifier(step: ActionStepType): JSX.Element | null {
    if (step.text) {
        return (
            <>
                “<strong>{truncate(step.text)}</strong>”
            </>
        )
    }
    if (step.selector) {
        return <strong className="font-mono">{truncate(step.selector)}</strong>
    }
    if (step.href) {
        return (
            <>
                link <strong className="font-mono">{truncate(stripHTTP(step.href))}</strong>
            </>
        )
    }
    return null
}

/**
 * One-line, scannable summary of a single action step for the actions list. Autocapture steps carry
 * their most identifying detail inline so a list of them isn't just a wall of "Autocapture".
 */
export function ActionStepSummary({ step }: { step: ActionStepType }): JSX.Element {
    switch (step.event) {
        case '$autocapture': {
            const identifier = autocaptureIdentifier(step)
            return identifier ? <>Autocapture on {identifier}</> : <>Autocapture</>
        }
        case '$pageview': {
            const url = truncate(stripHTTP(step.url || ''))
            const label =
                step.url_matching === 'regex'
                    ? 'Page view URL matches regex'
                    : step.url_matching === 'exact'
                      ? 'Page view URL matches exactly'
                      : 'Page view URL contains'
            return (
                <>
                    {label} <strong>{url}</strong>
                </>
            )
        }
        case '$screen': {
            const screenFilter = step.properties?.find(isScreenNameFilter)
            if (screenFilter && 'value' in screenFilter && screenFilter.value) {
                const operator =
                    'operator' in screenFilter ? (screenFilter.operator as ScreenNameMatching) : 'icontains'
                return (
                    <>
                        Screen name {SCREEN_NAME_MATCHING_LABEL[operator]}{' '}
                        <strong>
                            {Array.isArray(screenFilter.value)
                                ? screenFilter.value.join(', ')
                                : String(screenFilter.value)}
                        </strong>
                    </>
                )
            }
            return <>Mobile screen</>
        }
        case '':
        case null:
        case undefined:
            return <>Any event</>
        default:
            return (
                <>
                    Event: <strong>{step.event}</strong>
                </>
            )
    }
}

function Mono({ children }: { children: React.ReactNode }): JSX.Element {
    return <span className="font-mono">{children}</span>
}

/**
 * Full breakdown of every condition in a step, for the hover tooltip on the actions list. Surfaces the
 * selector / text / href / url / property filters that the one-line summary can't fit.
 */
export function ActionStepConditions({ step }: { step: ActionStepType }): JSX.Element {
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
                Text {stringMatchingVerb(step.text_matching)} <Mono>{step.text}</Mono>
            </li>
        )
    }
    if (step.href) {
        conditions.push(
            <li key="href">
                Link href {stringMatchingVerb(step.href_matching)} <Mono>{step.href}</Mono>
            </li>
        )
    }
    if (step.url) {
        conditions.push(
            <li key="url">
                URL {stringMatchingVerb(step.url_matching)} <Mono>{step.url}</Mono>
            </li>
        )
    }
    step.properties?.forEach((property, index) => {
        if ('key' in property) {
            conditions.push(
                <li key={`property-${index}`}>
                    <Mono>{property.key}</Mono> {genericOperatorToHumanName(property)}{' '}
                    <Mono>{propertyValueToHumanName(property.value)}</Mono>
                </li>
            )
        }
    })
    return (
        <div className="flex flex-col gap-1">
            <div>
                <ActionStepSummary step={step} />
            </div>
            {conditions.length > 0 && <ul className="list-disc pl-4 space-y-0.5 text-secondary">{conditions}</ul>}
        </div>
    )
}
