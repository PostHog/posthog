import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'
import { LemonPoeFilter } from './LemonPoeFilter'
import { poeFilterLogic } from './poeFilterLogic'
import { QuillPoeFilter } from './QuillPoeFilter'

interface PoeFilterProps {
    insightProps: InsightLogicProps
}

export interface PoeFilterControlProps {
    checked: boolean
    onChange: (checked: boolean) => void
    disabledReason?: string
}

export function PoeFilter({ insightProps }: PoeFilterProps): JSX.Element {
    const { poeMode } = useValues(poeFilterLogic(insightProps))
    const { hasDataWarehouseSeries } = useValues(insightVizDataLogic(insightProps))
    const { setPoeMode } = useActions(poeFilterLogic(insightProps))
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    const disabledReason = hasDataWarehouseSeries
        ? 'Data warehouse insights always use the latest table properties.'
        : undefined

    const props: PoeFilterControlProps = {
        checked: !!poeMode,
        onChange: (checked) => {
            if (checked) {
                setPoeMode('person_id_override_properties_joined')
            } else {
                setPoeMode(null)
            }
        },
        disabledReason,
    }
    return quillEnabled ? <QuillPoeFilter {...props} /> : <LemonPoeFilter {...props} />
}
