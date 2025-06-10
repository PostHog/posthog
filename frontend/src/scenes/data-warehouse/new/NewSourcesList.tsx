import { IconBell, IconCheck } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, lemonToast, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { SurveyEventName, SurveyEventProperties } from '~/types'

import { MANUAL_SOURCE_LINK_MAP, sourceWizardLogic } from './sourceWizardLogic'

export type NewSourcesListProps = {
    disableConnectedSources?: boolean
}

export function NewSourcesList({ disableConnectedSources }: NewSourcesListProps): JSX.Element {
    const { connectors } = useValues(sourceWizardLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const filteredConnectors = connectors.filter((n) => {
        return !(n.name === 'GoogleAds' && !featureFlags[FEATURE_FLAGS.GOOGLE_ADS_DWH])
    })

    return (
        <>
            <h2 className="mt-4">Managed data warehouse sources</h2>

            <p>
                Data will be synced to PostHog and regularly refreshed.{' '}
                <Link to="https://posthog.com/docs/cdp/sources">Learn more</Link>
            </p>
            <LemonTable
                dataSource={filteredConnectors}
                loading={false}
                disableTableWhileLoading={false}
                columns={[
                    {
                        title: 'Source',
                        width: 0,
                        render: function (_, sourceConfig) {
                            return <DataWarehouseSourceIcon type={sourceConfig.name} />
                        },
                    },
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, sourceConfig) => (
                            <div className="flex flex-col">
                                <span className="gap-1 text-sm font-semibold">
                                    {sourceConfig.label ?? sourceConfig.name}
                                </span>
                                {sourceConfig.unreleasedSource && (
                                    <span>Get notified when {sourceConfig.label} is available to connect</span>
                                )}
                            </div>
                        ),
                    },
                    {
                        key: 'actions',
                        render: (_, sourceConfig) => {
                            const isConnected = disableConnectedSources && sourceConfig.existingSource

                            return (
                                <div className="flex flex-row justify-end p-1">
                                    {isConnected && (
                                        <LemonTag type="success" className="my-4" size="medium">
                                            <IconCheck />
                                            Connected
                                        </LemonTag>
                                    )}
                                    {!isConnected && sourceConfig.unreleasedSource === true && (
                                        <LemonButton
                                            className="my-2"
                                            type="primary"
                                            icon={<IconBell />}
                                            onClick={() => {
                                                // https://us.posthog.com/project/2/surveys/0190ff15-5032-0000-722a-e13933c140ac
                                                posthog.capture(SurveyEventName.SENT, {
                                                    [SurveyEventProperties.SURVEY_ID]:
                                                        '0190ff15-5032-0000-722a-e13933c140ac',
                                                    [`${SurveyEventProperties.SURVEY_RESPONSE}_ad030277-3642-4abf-b6b0-7ecb449f07e8`]:
                                                        sourceConfig.label ?? sourceConfig.name,
                                                })
                                                posthog.capture('source_notify_me', {
                                                    source: sourceConfig.label ?? sourceConfig.name,
                                                })
                                                lemonToast.success('Notification registered successfully')
                                            }}
                                        >
                                            Notify me
                                        </LemonButton>
                                    )}
                                    {!isConnected && !sourceConfig.unreleasedSource && (
                                        <LemonButton
                                            to={urls.dataWarehouseSourceNew() + '?kind=' + sourceConfig.name}
                                            className="my-2"
                                            type="primary"
                                            disabledReason={
                                                disableConnectedSources && sourceConfig.existingSource
                                                    ? 'You have already connected this source'
                                                    : undefined
                                            }
                                        >
                                            Link
                                        </LemonButton>
                                    )}
                                </div>
                            )
                        },
                    },
                ]}
            />

            <h2 className="mt-4">Self-managed data warehouse sources</h2>

            <p>
                Data will be queried directly from your data source that you manage.{' '}
                <Link to="https://posthog.com/docs/cdp/sources">Learn more</Link>
            </p>
            <LemonTable
                dataSource={Object.entries(MANUAL_SOURCE_LINK_MAP).map(([type, name]) => ({
                    type,
                    name,
                }))}
                loading={false}
                disableTableWhileLoading={false}
                columns={[
                    {
                        title: 'Source',
                        width: 0,
                        render: (_, sourceConfig) => <DataWarehouseSourceIcon type={sourceConfig.type} />,
                    },
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, sourceConfig) => (
                            <span className="gap-1 text-sm font-semibold">{sourceConfig.name}</span>
                        ),
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, sourceConfig) => (
                            <div className="flex flex-row justify-end p-1">
                                <LemonButton
                                    to={urls.dataWarehouseSourceNew() + '?kind=' + sourceConfig.type}
                                    className="my-2"
                                    type="primary"
                                >
                                    Link
                                </LemonButton>
                            </div>
                        ),
                    },
                ]}
            />
        </>
    )
}
