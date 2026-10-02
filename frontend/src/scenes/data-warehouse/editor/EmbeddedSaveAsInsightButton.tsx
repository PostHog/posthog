import { useActions, useValues } from 'kea'

import { IconGraph } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { getSaveAsDisabledReason } from './saveAsDisabledReason'
import { sqlEditorLogic } from './sqlEditorLogic'

export function EmbeddedSaveAsInsightButton(): JSX.Element {
    const { insightLoading, isSourceQueryLastRun } = useValues(sqlEditorLogic)
    const { saveAsInsight } = useActions(sqlEditorLogic)
    const { response, responseError, responseLoading } = useValues(dataNodeLogic)
    const disabledReason = getSaveAsDisabledReason({
        insightLoading,
        isSourceQueryLastRun,
        responseLoading,
        responseError,
        response,
    })

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconGraph />}
            onClick={() => saveAsInsight()}
            disabledReason={disabledReason}
            data-attr="sql-editor-embedded-save-as-insight"
        >
            Save as insight
        </LemonButton>
    )
}
