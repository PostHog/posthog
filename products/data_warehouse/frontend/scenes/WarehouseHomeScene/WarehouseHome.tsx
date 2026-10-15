import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconX } from '@posthog/icons'
import { Button, Heading, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { WarehouseFirstAnswerChecklist } from './WarehouseFirstAnswerChecklist'
import { WarehouseGettingStarted } from './WarehouseGettingStarted'
import { WarehouseHealth } from './WarehouseHealth'
import { warehouseHomeLogic } from './warehouseHomeLogic'
import { WarehouseMoreSources } from './WarehouseMoreSources'
import { WarehouseQuestions } from './WarehouseQuestions'
import { WAREHOUSE_QUESTIONS_SECTION_ID } from './warehouseQuestionsContent'
import { WarehouseRecentRuns } from './WarehouseRecentRuns'
import { WarehouseStackMap } from './WarehouseStackMap'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseHome(): JSX.Element {
    const { gettingStartedHidden } = useValues(warehouseHomeLogic)
    const { hideGettingStarted, showGettingStarted } = useActions(warehouseHomeLogic)

    return (
        <div data-quill className="@container/warehouse-home flex flex-col gap-12">
            {!gettingStartedHidden && (
                <>
                    <div className="flex flex-col gap-2">
                        <div className="flex justify-end">
                            <Button
                                size="sm"
                                data-attr="warehouse-home-hide-getting-started"
                                onClick={() => {
                                    posthog.capture('warehouse getting started clicked', { target: 'hide' })
                                    hideGettingStarted()
                                }}
                            >
                                <IconX />
                                Hide getting started
                            </Button>
                        </div>
                        <div className="grid items-start gap-6 @4xl/warehouse-home:grid-cols-[1fr_minmax(0,22rem)]">
                            <div className="flex max-w-2xl flex-col gap-3">
                                <Heading render={<h1 />} size="2xl" className="m-0">
                                    PostHog data stack
                                </Heading>
                                <Text variant="muted">
                                    The data stack brings your business and PostHog data together. Once the data is in,
                                    you shape it with views and materialized views, query it with PostHog AI or the SQL
                                    editor, chart it in insights, and reach it from your editor over MCP.
                                </Text>
                                <div className="flex flex-wrap gap-2">
                                    <Button
                                        variant="primary"
                                        data-attr="warehouse-home-hero-choose-question"
                                        onClick={() => {
                                            posthog.capture('warehouse getting started clicked', {
                                                target: 'hero_choose_question',
                                            })
                                            document
                                                .getElementById(WAREHOUSE_QUESTIONS_SECTION_ID)
                                                ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                                        }}
                                    >
                                        Pick a question to answer
                                    </Button>
                                    <Button
                                        variant="outline"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={urls.dataWarehouseSourceNew()} />}
                                        data-attr="warehouse-home-hero-connect-source"
                                        onClick={() =>
                                            posthog.capture('warehouse getting started clicked', {
                                                target: 'hero_connect_source',
                                            })
                                        }
                                    >
                                        Connect a source
                                    </Button>
                                </div>
                            </div>
                            <WarehouseFirstAnswerChecklist />
                        </div>
                    </div>
                    <WarehouseGettingStarted />
                    <WarehouseStackMap />
                    <WarehouseQuestions />
                    <WarehouseMoreSources />
                </>
            )}
            <section aria-labelledby="warehouse-overview" className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Heading render={<h2 id="warehouse-overview" />} size="base" className="m-0">
                        Overview
                    </Heading>
                    {gettingStartedHidden && (
                        <Button
                            size="sm"
                            data-attr="warehouse-home-show-getting-started"
                            onClick={() => {
                                posthog.capture('warehouse getting started clicked', { target: 'show' })
                                showGettingStarted()
                            }}
                        >
                            Show getting started
                        </Button>
                    )}
                </div>
                <div className="grid gap-4 @3xl/warehouse-home:grid-cols-2">
                    <WarehouseHealth />
                    <WarehouseRecentRuns />
                </div>
            </section>
        </div>
    )
}
