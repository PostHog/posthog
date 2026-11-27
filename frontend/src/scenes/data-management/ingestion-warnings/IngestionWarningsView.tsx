import { useActions, useValues } from 'kea'

import * as readingIsMagicPng from '@posthog/brand/hoggies/png/reading-is-magic'
import { IconOpenSidebar } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { renderWarningDescription, warningDocsUrl, warningTypeLabel } from './ingestionWarningDisplay'
import { IngestionWarning, IngestionWarningSummary, ingestionWarningsLogic } from './ingestionWarningsLogic'
import { QuillIngestionWarnings } from './QuillIngestionWarnings'

const HedgehogReadingIsMagic = pngHoggie(readingIsMagicPng)

export function IngestionWarningsView(): JSX.Element {
    const { data, dataLoading, summaryDatasets, dates, searchQuery, showProductIntro } =
        useValues(ingestionWarningsLogic)
    const { setSearchQuery } = useActions(ingestionWarningsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <SceneContent data-attr="manage-events-table">
            <SceneTitleSection
                name={sceneConfigurations[Scene.IngestionWarnings].name}
                description={sceneConfigurations[Scene.IngestionWarnings].description}
                resourceType={{
                    type: sceneConfigurations[Scene.IngestionWarnings].iconType || 'default_icon_type',
                }}
            />
            {todayRailNav ? (
                <QuillIngestionWarnings />
            ) : showProductIntro ? (
                <ProductIntroduction
                    thingName="ingestion warning"
                    isEmpty={true}
                    titleOverride="Nice! No ingestion warnings in the past 30 days"
                    description="Your incoming events look clean. If we detect any issues with your data, we'll show them here."
                    docsURL="https://posthog.com/docs/data/data-management#ingestion-warnings"
                    customHog={HedgehogReadingIsMagic}
                    actionElementOverride={
                        <LemonButton
                            type="primary"
                            to={urls.eventDefinitions()}
                            data-attr="ingestion-warnings-empty-state-events"
                            sideIcon={<IconOpenSidebar className="w-4 h-4" />}
                        >
                            Explore your events
                        </LemonButton>
                    }
                />
            ) : (
                <SceneSection>
                    <LemonInput
                        fullWidth
                        value={searchQuery}
                        onChange={setSearchQuery}
                        type="search"
                        placeholder="Try pasting a person or session id or an ingestion warning type"
                    />
                    <LemonTable
                        dataSource={data}
                        loading={dataLoading}
                        columns={[
                            {
                                title: 'Warning',
                                dataIndex: 'type',
                                render: function Render(_, summary: IngestionWarningSummary) {
                                    return (
                                        <>
                                            {warningTypeLabel(summary.type)} (
                                            <Link to={warningDocsUrl(summary.type)}>docs)</Link>
                                        </>
                                    )
                                },
                            },
                            {
                                title: 'Graph',
                                render: function Render(_, summary: IngestionWarningSummary) {
                                    return (
                                        <Sparkline
                                            className="h-8"
                                            labels={dates}
                                            data={summaryDatasets[summary.type]}
                                        />
                                    )
                                },
                            },
                            {
                                title: 'Events',
                                dataIndex: 'count',
                                align: 'right',
                                sorter: (a, b) => a.count - b.count,
                            },
                            {
                                title: 'Last Seen',
                                dataIndex: 'lastSeen',
                                render: function Render(_, summary: IngestionWarningSummary) {
                                    return <TZLabel time={summary.lastSeen} showSeconds />
                                },
                                align: 'right',
                                sorter: (a, b) => (new Date(a.lastSeen) > new Date(b.lastSeen) ? 1 : -1),
                            },
                        ]}
                        expandable={{
                            expandedRowRender: RenderNestedWarnings,
                        }}
                        defaultSorting={{
                            columnKey: 'lastSeen',
                            order: -1,
                        }}
                        noSortingCancellation
                    />
                </SceneSection>
            )}
        </SceneContent>
    )
}

function RenderNestedWarnings(warningSummary: IngestionWarningSummary): JSX.Element {
    return (
        <LemonTable
            dataSource={warningSummary.warnings}
            columns={[
                {
                    title: 'Description',
                    key: 'description',
                    render: function Render(_, warning: IngestionWarning) {
                        return renderWarningDescription(warning)
                    },
                },
                {
                    title: 'Time',
                    dataIndex: 'timestamp',
                    render: function Render(_, warning: IngestionWarning) {
                        return <TZLabel time={warning.timestamp} showSeconds />
                    },
                    align: 'right',
                },
            ]}
            embedded
            showHeader={false}
            pagination={{
                // In production this list can be huge - we don't want to render all of them at once
                pageSize: 20,
            }}
        />
    )
}
