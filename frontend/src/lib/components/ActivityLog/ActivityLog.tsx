import './ActivityLog.scss'

import useSize from '@react-hook/size'
import clsx from 'clsx'
import { useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonTabs } from '@posthog/lemon-ui'

import { ActivityLogLogicProps, activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { ActivityChange, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ProductKey } from '~/types'

import MonacoDiffEditor from '../MonacoDiffEditor'
import { PayGateMini } from '../PayGateMini/PayGateMini'
import { ProductIntroduction } from '../ProductIntroduction/ProductIntroduction'

export type ActivityLogProps = ActivityLogLogicProps & {
    startingPage?: number
    caption?: string | JSX.Element
}

const Empty = ({ scope }: { scope: string | string[] }): JSX.Element => {
    const noun = (Array.isArray(scope) ? scope[0] : scope)
        .replace(/([A-Z])/g, ' $1')
        .trim()
        .toLowerCase()

    return (
        <ProductIntroduction
            productName={noun.toUpperCase()}
            productKey={ProductKey.HISTORY}
            thingName="history record"
            description={`History shows any ${noun} changes that have been made. After making changes you'll see them logged here.`}
            isEmpty={true}
        />
    )
}

export const SkeletonLog = (): JSX.Element => {
    return (
        <div className="ActivityLogRow items-start">
            <LemonSkeleton.Circle />
            <div className="details deprecated-space-y-4 mt-2">
                <LemonSkeleton className="w-1/2 h-4" />
                <LemonSkeleton />
            </div>
        </div>
    )
}

const Loading = (): JSX.Element => {
    return (
        <>
            <SkeletonLog />
            <SkeletonLog />
            <SkeletonLog />
            <SkeletonLog />
        </>
    )
}

export type ActivityLogTabs = 'extended description' | 'diff' | 'raw'

const ActivityLogDiff = ({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element => {
    const changes = logItem.unprocessed?.detail.changes

    return (
        <div className="flex flex-col deprecated-space-y-2 px-2 py-1">
            <div className="flex flex-col deprecated-space-y-2">
                {changes?.length ? (
                    changes.map((change, i) => {
                        return (
                            <JsonDiffViewer key={i} field={change.field} before={change.before} after={change.after} />
                        )
                    })
                ) : (
                    <div className="text-secondary">This item has no changes to compare</div>
                )}
            </div>
        </div>
    )
}

interface JsonDiffViewerProps {
    field: string | undefined
    before: ActivityChange['before']
    after: ActivityChange['after']
}

const JsonDiffViewer = ({ field, before, after }: JsonDiffViewerProps): JSX.Element => {
    const containerRef = useRef<HTMLDivElement>(null)
    const [width] = useSize(containerRef)
    return (
        <div ref={containerRef} className="flex flex-col space-y-2 w-full">
            {field ? <h2>{field}</h2> : null}
            <MonacoDiffEditor
                original={JSON.stringify(before, null, 2)}
                modified={JSON.stringify(after, null, 2)}
                language="json"
                width={width}
                options={{
                    renderOverviewRuler: false,
                    scrollBeyondLastLine: false,
                    hideUnchangedRegions: {
                        enabled: true,
                        contextLineCount: 3,
                        minimumLineCount: 3,
                        revealLineCount: 20,
                    },
                    diffAlgorithm: 'advanced',
                }}
            />
        </div>
    )
}

export const ActivityLogRow = ({ logItem }: { logItem: HumanizedActivityLogItem }): JSX.Element => {
    const [isExpanded, setIsExpanded] = useState(false)
    const [activeTab, setActiveTab] = useState<ActivityLogTabs>('diff')
    return (
        <div className={clsx('flex flex-col px-1 py-0.5', isExpanded && 'border rounded')}>
            <div
                className={clsx('ActivityLogRow flex deprecated-space-x-2', logItem.unread && 'ActivityLogRow--unread')}
            >
                <ProfilePicture
                    showName={false}
                    user={{
                        first_name: logItem.isSystem ? logItem.name : undefined,
                        email: logItem.email ?? undefined,
                    }}
                    type={logItem.isSystem ? 'system' : 'person'}
                    size="xl"
                />
                <div className="ActivityLogRow__details flex-grow">
                    <div className="ActivityLogRow__description">{logItem.description}</div>
                    {logItem.extendedDescription && (
                        <div className="ActivityLogRow__description__extended">{logItem.extendedDescription}</div>
                    )}
                    <div className="text-secondary">
                        <TZLabel time={logItem.created_at} />
                    </div>
                </div>
                <LemonButton
                    noPadding={true}
                    icon={isExpanded ? <IconCollapse /> : <IconExpand />}
                    onClick={() => setIsExpanded(!isExpanded)}
                    active={isExpanded}
                />
            </div>
            {isExpanded && (
                <div className="px-1 py-0.5">
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={(key) => setActiveTab(key as ActivityLogTabs)}
                        tabs={[
                            logItem.extendedDescription
                                ? {
                                      key: 'extended description',
                                      label: 'Extended Description',
                                      tooltip:
                                          'Some activities have a more detailed description that is not shown when collapsed.',
                                      content: (
                                          <div>
                                              {logItem.extendedDescription
                                                  ? logItem.extendedDescription
                                                  : 'This item has no extended description'}
                                          </div>
                                      ),
                                  }
                                : false,
                            {
                                key: 'diff',
                                label: 'Diff',
                                tooltip:
                                    'Show the diff of the changes made to the item. Each activity item could have more than one change.',
                                content: <ActivityLogDiff logItem={logItem} />,
                            },
                            {
                                key: 'raw',
                                label: 'Raw',
                                tooltip: 'Show the raw data of the activity item.',
                                content: (
                                    <div>
                                        <pre>{JSON.stringify(logItem.unprocessed, null, 2)}</pre>
                                    </div>
                                ),
                            },
                        ]}
                    />
                </div>
            )}
        </div>
    )
}

export const ActivityLog = ({ scope, id, caption, startingPage = 1 }: ActivityLogProps): JSX.Element | null => {
    const logic = activityLogLogic({ scope, id, caption, startingPage })
    const { humanizedActivity, activityLoading, pagination } = useValues(logic)
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { billingLoading } = useValues(billingLogic)

    const paginationState = usePagination(humanizedActivity || [], pagination)

    return (
        <div className="ActivityLog">
            {caption && <div className="page-caption">{caption}</div>}
            {(activityLoading && humanizedActivity.length === 0) || billingLoading ? (
                <Loading />
            ) : (
                <PayGateMini
                    feature={AvailableFeature.AUDIT_LOGS}
                    overrideShouldShowGate={user?.is_impersonated || !!featureFlags[FEATURE_FLAGS.AUDIT_LOGS_ACCESS]}
                >
                    {humanizedActivity.length === 0 ? (
                        <Empty scope={scope} />
                    ) : (
                        <>
                            <div className="deprecated-space-y-2">
                                {humanizedActivity.map((logItem, index) => (
                                    <ActivityLogRow key={index} logItem={logItem} />
                                ))}
                            </div>
                            <LemonDivider />
                            <PaginationControl {...paginationState} nouns={['activity', 'activities']} />
                        </>
                    )}
                </PayGateMini>
            )}
        </div>
    )
}
