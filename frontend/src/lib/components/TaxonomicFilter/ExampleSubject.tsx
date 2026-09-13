import { useValues } from 'kea'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

import { taxonomicExampleBrowserLogic } from './taxonomicExampleBrowserLogic'
import { TaxonomicFilterGroupType } from './types'

const ORDINAL_SUFFIXES: Record<Intl.LDMLPluralRule, string> = {
    one: 'st',
    two: 'nd',
    few: 'rd',
    other: 'th',
    zero: 'th',
    many: 'th',
}

function ordinal(position: number): string {
    return `${position}${ORDINAL_SUFFIXES[new Intl.PluralRules('en', { type: 'ordinal' }).select(position)]}`
}

/** Render inside an inline element: a flex parent drops the spaces between the text nodes. */
export function ExampleSubject({ position }: { position: number }): JSX.Element {
    const { exampleSource, exampleNoun } = useValues(taxonomicExampleBrowserLogic)
    const rank = position === 1 ? 'most' : `${ordinal(position)} most`

    switch (exampleSource?.kind) {
        case 'person':
            return <>{rank} recently seen person</>
        case 'group':
            return (
                <>
                    {rank} recently created {exampleNoun.singular}
                </>
            )
        case 'event':
            return exampleSource.eventNames.length === 1 ? (
                <>
                    {rank} recent{' '}
                    <PropertyKeyInfo value={exampleSource.eventNames[0]} type={TaxonomicFilterGroupType.Events} /> event
                </>
            ) : (
                <>{rank} recent matching event</>
            )
        default:
            return <>{rank} recent event</>
    }
}
