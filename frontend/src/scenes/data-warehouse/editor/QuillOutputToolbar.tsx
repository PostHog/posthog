import { IconColumns, IconGear, IconGraph, IconShare } from '@posthog/icons'
import {
    Button,
    Tabs,
    TabsList,
    TabsTrigger,
    Text,
    Toggle,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { IconTableChart } from 'lib/lemon-ui/icons'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import type { ExportContext } from '~/types'

import { OutputTab } from './outputPaneLogic'
import { QuillChartTypeMenu } from './QuillChartTypeMenu'
import { QuillResultsExportMenu } from './QuillResultsExportMenu'

export interface QuillOutputToolbarProps {
    activeTab: OutputTab
    onActiveTabChange: (tab: OutputTab) => void
    response: HogQLQueryResponse | undefined
    rows: Record<string, any>[]
    hasColumns: boolean
    exportContext: ExportContext | undefined
    hasQueryInput: boolean
    isEmbeddedMode: boolean
    settingsOpen: boolean
    onShareTab?: () => void
    onToggleChartSettingsPanel: () => void
}

/**
 * The results pane's tab strip and actions in the quill editor. In split view the results and the
 * chart show side by side, so the tabs give way to one label and both sets of actions show.
 */
export function QuillOutputToolbar({
    activeTab,
    onActiveTabChange,
    response,
    rows,
    hasColumns,
    exportContext,
    hasQueryInput,
    isEmbeddedMode,
    settingsOpen,
    onShareTab,
    onToggleChartSettingsPanel,
}: QuillOutputToolbarProps): JSX.Element {
    const splitView = activeTab === OutputTab.Both
    const showResultsActions = activeTab !== OutputTab.Visualization
    const showChartActions = activeTab !== OutputTab.Results
    const noResultsReason = !hasColumns ? 'No results to visualize' : undefined

    return (
        <div className="flex min-h-10 shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b px-2">
            {splitView ? (
                <Text size="xs" className="m-0 flex h-10 items-center px-2 font-medium">
                    Results and chart
                </Text>
            ) : (
                <Tabs value={activeTab} onValueChange={(value) => onActiveTabChange(value as OutputTab)}>
                    <TabsList variant="line" className="h-10">
                        <TabsTrigger value={OutputTab.Results}>
                            <IconTableChart />
                            Results
                        </TabsTrigger>
                        <TabsTrigger value={OutputTab.Visualization}>
                            <IconGraph />
                            Chart
                        </TabsTrigger>
                    </TabsList>
                </Tabs>
            )}
            <div className="ms-auto flex flex-wrap items-center gap-1">
                {showChartActions ? (
                    <>
                        <QuillChartTypeMenu disabledReason={noResultsReason} />
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Toggle
                                        size="icon"
                                        pressed={settingsOpen}
                                        onPressedChange={() => onToggleChartSettingsPanel()}
                                        disabled={!!noResultsReason}
                                        aria-label="Chart settings"
                                        data-attr="sql-editor-visualization-settings-button"
                                    />
                                }
                            >
                                <IconGear />
                            </TooltipTrigger>
                            <TooltipContent>{noResultsReason ?? 'Chart settings'}</TooltipContent>
                        </Tooltip>
                    </>
                ) : null}
                {showResultsActions ? (
                    <QuillResultsExportMenu response={response} rows={rows} exportContext={exportContext} />
                ) : null}
                {!isEmbeddedMode && onShareTab ? (
                    <Button
                        size="icon"
                        onClick={onShareTab}
                        disabledReason={!hasQueryInput ? 'No query to share' : undefined}
                        aria-label="Copy a link to this query"
                        tooltip="Copy a link to this query"
                        id="sql-editor-share"
                        data-attr="sql-editor-share"
                    >
                        <IconShare />
                    </Button>
                ) : null}
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Toggle
                                size="icon"
                                pressed={splitView}
                                onPressedChange={(pressed) =>
                                    onActiveTabChange(pressed ? OutputTab.Both : OutputTab.Results)
                                }
                                aria-label="Show results and chart side by side"
                                data-attr="sql-editor-output-split-toggle"
                            />
                        }
                    >
                        <IconColumns />
                    </TooltipTrigger>
                    <TooltipContent>Show results and chart side by side</TooltipContent>
                </Tooltip>
            </div>
        </div>
    )
}
