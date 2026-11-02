import { BindLogic, useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { MetricsWidgetQueryEditor } from 'products/metrics/frontend/widgets/MetricsWidgetQueryEditor'

import { getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import { EditWidgetModalTileDetailsSection } from '../EditWidgetModalTileDetailsSection'
import type { DashboardWidgetEditModalProps } from '../registry'
import { editMetricsWidgetModalLogic } from './editMetricsWidgetModalLogic'
import { metricsWidgetDefaultTitle } from './metricsWidgetConfig'

function EditMetricsWidgetModalContents(): JSX.Element {
    const {
        tileName,
        tileDescription,
        query,
        saving,
        saveDisabledReason,
        fieldErrors,
        onClose,
        defaultTitle,
        hasUnsavedChanges,
    } = useValues(editMetricsWidgetModalLogic)
    const { setTileName, setTileDescription, setQuery, setHasUnrunQueryText, submit, requestClose } =
        useActions(editMetricsWidgetModalLogic)
    const languagesEnabled = useFeatureFlag('METRICS_QUERY_LANGUAGES')

    return (
        <LemonModal
            isOpen
            onClose={requestClose}
            hasUnsavedInput={hasUnsavedChanges}
            title="Metric widget"
            description={
                languagesEnabled
                    ? 'Pick a metric, or write a PromQL or SQL query, and choose how to chart it.'
                    : 'Pick a metric and choose how to chart it.'
            }
            width={1100}
            footer={
                <>
                    <div className="flex-1" />
                    <LemonButton type="secondary" onClick={onClose} disabled={saving}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={saving}
                        disabledReason={saveDisabledReason}
                        onClick={() => submit()}
                        data-attr="metrics-widget-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <section className="flex flex-col gap-3">
                    <h5 className="text-sm font-semibold m-0">{getDashboardWidgetGroupLabel('metrics')}</h5>
                    {fieldErrors.query ? <LemonBanner type="error">{fieldErrors.query}</LemonBanner> : null}
                    <MetricsWidgetQueryEditor
                        query={query}
                        setQuery={setQuery}
                        onUnrunTextChange={setHasUnrunQueryText}
                    />
                    <p className="text-xs text-secondary m-0">
                        When the dashboard has a date range, the tile uses it instead of the range set here.
                    </p>
                </section>
                <LemonDivider className="my-0" />
                <EditWidgetModalTileDetailsSection
                    tileName={tileName}
                    tileDescription={tileDescription}
                    defaultTitle={metricsWidgetDefaultTitle({ query }) ?? defaultTitle}
                    saving={saving}
                    setTileName={setTileName}
                    setTileDescription={setTileDescription}
                />
            </div>
        </LemonModal>
    )
}

export function EditMetricsWidgetModal({
    isOpen,
    onClose,
    config,
    onSave,
    name,
    defaultTitle,
    description,
}: DashboardWidgetEditModalProps): JSX.Element | null {
    if (!isOpen) {
        return null
    }

    return (
        <BindLogic
            logic={editMetricsWidgetModalLogic}
            props={{ onClose, config, onSave, name, defaultTitle, description }}
        >
            <EditMetricsWidgetModalContents />
        </BindLogic>
    )
}
