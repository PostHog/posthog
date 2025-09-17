import { useActions, useValues } from 'kea'

import { LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { InsightLogicProps } from '~/types'

import { poeFilterLogic } from './poeFilterLogic'

interface PoeFilterProps {
    insightProps: InsightLogicProps
}

export function PoeFilter({ insightProps }: PoeFilterProps): JSX.Element {
    const { poeMode } = useValues(poeFilterLogic(insightProps))
    const { setPoeMode } = useActions(poeFilterLogic(insightProps))

    return (
        <>
            <div className="flex items-center gap-1">
                <LemonLabel
                    info="Overides the default person properties mode for this insight to use person properties from query time instead of from the time of the event. This can be useful for specific queries that require person data that comes in after the event in question, but it slows down performance considerably, so use it with care."
                    infoLink="https://posthog.com/docs/how-posthog-works/queries#filtering-on-person-properties"
                >
                    Use person properties from query time
                </LemonLabel>
                <LemonSwitch
                    className="m-2"
                    onChange={(checked) => {
                        if (checked) {
                            setPoeMode('person_id_override_properties_joined')
                        } else {
                            setPoeMode(null)
                        }
                    }}
                    checked={!!poeMode}
                />
            </div>
        </>
    )
}
