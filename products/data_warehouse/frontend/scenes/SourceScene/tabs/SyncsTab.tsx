import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { LemonButton, LemonDivider, LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ExternalDataJob, ExternalDataJobStatus } from '~/types'

import { failedDestinationFor } from 'products/data_warehouse/frontend/shared/components/destinationFailure'
import { JobDestinations } from 'products/data_warehouse/frontend/shared/components/JobDestinations'
import { JobLogsViewer } from 'products/data_warehouse/frontend/shared/components/JobLogsViewer'
import { destinationLookupLogic } from 'products/data_warehouse/frontend/shared/logics/destinationLookupLogic'

import { sourceSettingsLogic } from './sourceSettingsLogic'

const StatusTagSetting: Record<ExternalDataJob['status'], LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Failed: 'danger',
    [ExternalDataJobStatus.BillingLimits]: 'danger',
    [ExternalDataJobStatus.BillingLimitTooLow]: 'danger',
}

interface SyncsTabProps {
    id: string
    // When set, the tab is locked to this single schema's jobs and the schema filter is hidden.
    // Used by the schema detail page's Syncs tab.
    lockedSchema?: string
}

export const SyncsTab = ({ id, lockedSchema }: SyncsTabProps): JSX.Element => {
    const logic = sourceSettingsLogic({ id, availableSources: {} })
    const { source, jobs, jobsLoading, canLoadMoreJobs, selectedSchemas } = useValues(logic)
    const { loadJobs, loadMoreJobs, setSelectedSchemas } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { loadDestinations } = useActions(destinationLookupLogic)
    const { destinationsById, destinationsLoading } = useValues(destinationLookupLogic)
    // Without the flag every run goes to the warehouse alone, so a column of identical logos
    // would be noise.
    const showDestinations = !!featureFlags[FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION]

    useEffect(() => {
        if (showDestinations) {
            loadDestinations()
        }
    }, [showDestinations, loadDestinations])

    // Lock to a single schema when asked, otherwise apply a `?schema=<name>` deep link once on
    // mount so links from the schemas list and the schema configuration page land here filtered.
    useEffect(() => {
        if (!lockedSchema) {
            const schemaParam = router.values.searchParams.schema
            if (schemaParam) {
                setSelectedSchemas(Array.isArray(schemaParam) ? schemaParam : [schemaParam])
            }
            return
        }
        setSelectedSchemas([lockedSchema])
        // `sourceSettingsLogic` is keyed by source id and shared with the source page, which can
        // keep it mounted past this tab. Release the lock on the way out, or the source's own
        // Syncs tab stays filtered to this one schema.
        return () => {
            if (logic.isMounted()) {
                logic.actions.setSelectedSchemas([])
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useEffect(() => {
        if (!source || source.access_method === 'direct') {
            return
        }

        void loadJobs()
    }, [loadJobs, source])

    const schemaOptions = [...(source?.schemas ?? [])]
        .sort((a, b) => (a.label ?? a.name).localeCompare(b.label ?? b.name))
        .map((schema) => ({
            key: schema.name,
            label: schema.label ?? schema.name,
        }))

    return (
        <>
            {!lockedSchema && schemaOptions.length > 1 && (
                <>
                    <div className="flex items-center gap-2 mb-2">
                        <LemonLabel>Schema</LemonLabel>
                        <LemonInputSelect
                            mode="multiple"
                            bulkActions="select-and-clear-all"
                            displayMode="count"
                            size="small"
                            value={selectedSchemas}
                            onChange={setSelectedSchemas}
                            options={schemaOptions}
                            placeholder="All"
                            allowCustomValues={false}
                        />
                    </div>
                    <LemonDivider className="my-4" />
                </>
            )}
            <LemonTable
                hideScrollbar
                dataSource={jobs}
                rowKey="id"
                loading={jobsLoading}
                disableTableWhileLoading={false}
                columns={[
                    {
                        title: 'Schema',
                        render: (_, job) => {
                            const name = job.schema.label ?? job.schema.name
                            // CDC `cdc_table_mode='both'` produces two ExternalDataJob rows per sync —
                            // one for the consolidated table, one for the cdc-only history table.
                            // Show a badge so they're distinguishable in the UI.
                            const cdcWriteModeLabel =
                                job.cdc_write_mode === 'scd2_append'
                                    ? 'CDC history'
                                    : job.cdc_write_mode === 'incremental_merge'
                                      ? 'consolidated'
                                      : null
                            return (
                                <span className="flex items-center gap-1">
                                    {name}
                                    {job.schema.sync_type === 'cdc' && (
                                        <LemonTag type="highlight" size="small">
                                            CDC
                                        </LemonTag>
                                    )}
                                    {cdcWriteModeLabel && (
                                        <LemonTag type="muted" size="small">
                                            {cdcWriteModeLabel}
                                        </LemonTag>
                                    )}
                                </span>
                            )
                        },
                    },
                    {
                        title: 'Status',
                        render: (_, job) => {
                            const tagContent = (
                                <LemonTag type={StatusTagSetting[job.status] || 'default'}>{job.status}</LemonTag>
                            )
                            return (
                                <span className="flex items-center gap-1">
                                    {job.latest_error && job.status === ExternalDataJobStatus.Failed ? (
                                        <Tooltip title={job.latest_error} interactive>
                                            {tagContent}
                                        </Tooltip>
                                    ) : (
                                        tagContent
                                    )}
                                    {job.billable === false && (
                                        <Tooltip title="You're not charged for this sync. These are usually system-initiated runs, like rebuilding a table after an issue on our side.">
                                            <LemonTag type="muted" size="small">
                                                Non-billable
                                            </LemonTag>
                                        </Tooltip>
                                    )}
                                </span>
                            )
                        },
                    },
                    {
                        title: 'Row count',
                        tooltip:
                            'Rows read from the source. A run reads them once however many destinations it writes to.',
                        render: (_, job) => {
                            return job.rows_synced.toLocaleString()
                        },
                    },
                    ...(showDestinations
                        ? [
                              {
                                  title: 'Destinations',
                                  render: (_: any, job: ExternalDataJob) => (
                                      <JobDestinations
                                          destinationIds={job.destination_ids ?? []}
                                          destinationsById={destinationsById}
                                          loading={destinationsLoading}
                                          failedDestinationId={
                                              job.status === ExternalDataJobStatus.Failed && job.latest_error
                                                  ? failedDestinationFor(
                                                        job.latest_error,
                                                        job.destination_ids ?? [],
                                                        destinationsById
                                                    )?.id
                                                  : undefined
                                          }
                                      />
                                  ),
                              },
                          ]
                        : []),
                    {
                        title: 'Synced at',
                        render: (_, job) => {
                            return <TZLabel time={job.created_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                        },
                    },
                ]}
                expandable={
                    jobs.length > 0
                        ? {
                              expandedRowRender: (job) => (
                                  <div className="p-4">
                                      <JobLogsViewer
                                          jobId={job.id}
                                          schemaId={job.schema.id}
                                          workflowRunId={job.workflow_run_id}
                                          createdAt={job.created_at}
                                          finishedAt={job.finished_at}
                                      />
                                  </div>
                              ),
                              rowExpandable: () => true,
                              noIndent: true,
                          }
                        : undefined
                }
                footer={
                    <LemonButton
                        onClick={loadMoreJobs}
                        type="tertiary"
                        fullWidth
                        center
                        disabledReason={!canLoadMoreJobs ? "There's nothing more to load" : undefined}
                    >
                        {canLoadMoreJobs ? `Load older jobs` : 'No older jobs'}
                    </LemonButton>
                }
            />
        </>
    )
}
