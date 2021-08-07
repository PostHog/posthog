import { Alert, Button } from "antd"
import clsx from "clsx"
import { useActions, useValues } from "kea"
import { FEATURE_FLAGS } from "lib/constants"
import { featureFlagLogic } from "lib/logic/featureFlagLogic"
import { Loading } from "lib/utils"
import React from "react"
import { Funnel } from "scenes/funnels/Funnel"
import { funnelLogic } from "scenes/funnels/funnelLogic"
import { FunnelVizType } from "~/types"
import { FunnelInvalidFiltersEmptyState, FunnelEmptyState } from "./EmptyStates"

export function FunnelInsight(): JSX.Element {
    const {
        isValidFunnel,
        isLoading,
        filters: { funnel_viz_type },
        areFiltersValid,
        filtersDirty,
        clickhouseFeaturesEnabled,
    } = useValues(funnelLogic({}))
    const { loadResults } = useActions(funnelLogic({}))
    const { featureFlags } = useValues(featureFlagLogic)

    const renderFunnel = (): JSX.Element => {
        if (isValidFunnel) {
            return <Funnel filters={{ funnel_viz_type }} />
        }
        if (!areFiltersValid) {
            return <FunnelInvalidFiltersEmptyState />
        }
        return isLoading ? <div style={{ height: 50 }} /> : <FunnelEmptyState />
    }

    return (
        <div
            className={clsx('funnel-insights-container', {
                'non-empty-state':
                    isValidFunnel &&
                    areFiltersValid &&
                    (!featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] || funnel_viz_type === FunnelVizType.Trends),
                'dirty-state': filtersDirty && !clickhouseFeaturesEnabled,
            })}
        >
            {filtersDirty && areFiltersValid && !isLoading && !clickhouseFeaturesEnabled ? (
                <div className="dirty-label">
                    <Alert
                        message={
                            <>
                                The filters have changed.{' '}
                                <Button onClick={loadResults}>Click to recalculate the funnel.</Button>
                            </>
                        }
                        type="warning"
                        showIcon
                    />
                </div>
            ) : null}
            {isLoading && <Loading />}
            {renderFunnel()}
        </div>
    )
}