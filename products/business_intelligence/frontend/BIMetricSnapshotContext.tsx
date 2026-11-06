import { LemonBanner, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { BIConfig } from '~/queries/schema/schema-business-intelligence'

import { metricParameterDrafts } from './biMetricParametersLogic'

export function BIMetricSnapshotContext({ config }: { config: BIConfig }): JSX.Element {
    const context = config.catalogMetricContext
    const approved = context?.status === 'approved' && !context.isDrifted
    return (
        <LemonBanner type={context && !approved ? 'warning' : 'info'}>
            <div className="flex min-w-0 flex-col gap-2">
                <div>
                    This is a SQL copy.{' '}
                    {metricParameterDrafts(config.querySnapshot).length
                        ? 'Edit its parameters below, or use View SQL to change the query.'
                        : 'Use View SQL to edit its dates or grouping in the SQL editor.'}{' '}
                    Catalog changes won't update this copy.
                </div>
                {context ? (
                    <div className="flex flex-wrap items-center gap-2 break-words">
                        <span>Catalog status when copied (unverified):</span>
                        <LemonTag type={approved ? 'default' : 'warning'}>
                            {context.isDrifted ? 'Drifted' : context.status === 'approved' ? 'Approved' : 'Proposed'}
                        </LemonTag>
                        {context.unit && <span>Unit: {context.unit}</span>}
                        {context.owner && <span className="break-all">Owner: {context.owner}</span>}
                    </div>
                ) : (
                    <span>Catalog status was not recorded for this copy.</span>
                )}
                {context && (
                    <span>
                        These saved details are unverified. Check the current catalog entry before using this copy.
                    </span>
                )}
                {config.catalogMetric && (
                    <Link to={urls.dataCatalogMetric(config.catalogMetric)}>View current catalog entry</Link>
                )}
            </div>
        </LemonBanner>
    )
}
