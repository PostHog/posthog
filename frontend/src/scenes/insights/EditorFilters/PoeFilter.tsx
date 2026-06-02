import { useActions, useValues } from 'kea'

import { LemonBanner, LemonDisabledArea, LemonLabel, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'
import { PoeModeTypes, poeFilterLogic } from './poeFilterLogic'

type PersonPropertyModeValue = NonNullable<PoeModeTypes> | 'project_default'

const PERSON_PROPERTY_MODE_OPTIONS: LemonSelectOption<PersonPropertyModeValue>[] = [
    { value: 'project_default', label: 'Project default' },
    { value: 'person_id_override_properties_on_events', label: 'Event-time snapshot' },
    { value: 'person_id_override_properties_joined', label: 'Latest person profile' },
]

interface PoeFilterProps {
    insightProps: InsightLogicProps
}

export function PoeFilter({ insightProps }: PoeFilterProps): JSX.Element {
    const { poeMode } = useValues(poeFilterLogic(insightProps))
    const { hasDataWarehouseSeries } = useValues(insightVizDataLogic(insightProps))
    const { setPoeMode } = useActions(poeFilterLogic(insightProps))
    const disabledReason = hasDataWarehouseSeries
        ? 'Data warehouse insights always use the latest table properties.'
        : undefined

    return (
        <div className="deprecated-space-y-2">
            <LemonDisabledArea className="deprecated-space-y-2 w-fit" disabledReason={disabledReason}>
                <LemonLabel
                    info="Overrides the default person property mode for this insight. Event-time snapshot uses person properties stored on the event row. Latest person profile joins the current person profile at query time."
                    infoLink="https://posthog.com/docs/how-posthog-works/queries#filtering-on-person-properties"
                >
                    Person property mode
                </LemonLabel>
                <LemonSelect
                    size="small"
                    fullWidth
                    disabledReason={disabledReason}
                    value={poeMode ?? 'project_default'}
                    onChange={(value) => {
                        setPoeMode(value === 'project_default' ? null : value)
                    }}
                    options={PERSON_PROPERTY_MODE_OPTIONS}
                    dropdownMatchSelectWidth={false}
                    data-attr="person-property-mode-select"
                    truncateText={{ maxWidthClass: 'max-w-64' }}
                />
            </LemonDisabledArea>
            {poeMode === 'person_id_override_properties_joined' ? (
                <LemonBanner type="warning">
                    This insight now joins the current person profile at query time. Historical events are not
                    rewritten, so changing a person property can change past-looking results.
                </LemonBanner>
            ) : null}
        </div>
    )
}
