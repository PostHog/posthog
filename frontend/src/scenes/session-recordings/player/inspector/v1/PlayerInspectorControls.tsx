import { LemonButton, LemonInput, LemonSwitch, LemonSelect } from '@posthog/lemon-ui'
import { Tooltip } from 'antd'
import { useValues, useActions } from 'kea'
import { IconInfo, IconTerminal, UnverifiedEvent } from 'lib/components/icons'
import { capitalizeFirstLetter } from 'lib/utils'
import { SessionRecordingPlayerTab } from '~/types'
import { IconWindow } from '../../icons'
import { playerMetaLogic } from '../../playerMetaLogic'
import { playerSettingsLogic } from '../../playerSettingsLogic'
import { SessionRecordingPlayerLogicProps } from '../../sessionRecordingPlayerLogic'
import { playerInspectorLogic } from '../playerInspectorLogic'
import { consoleLogsListLogic } from './consoleLogsListLogic'
import { eventsListLogic } from './eventsListLogic'

const TabToIcon = {
    [SessionRecordingPlayerTab.EVENTS]: <UnverifiedEvent />,
    [SessionRecordingPlayerTab.CONSOLE]: <IconTerminal />,
}

export function PlayerInspectorControls({
    sessionRecordingId,
    playerKey,
    matching,
}: SessionRecordingPlayerLogicProps): JSX.Element {
    const logicProps = { sessionRecordingId, playerKey }
    const { windowIdFilter, tab, tabsState } = useValues(playerInspectorLogic(logicProps))
    const { setWindowIdFilter, setTab } = useActions(playerInspectorLogic(logicProps))
    const { showOnlyMatching } = useValues(playerSettingsLogic)
    const { setShowOnlyMatching } = useActions(playerSettingsLogic)
    const { eventListLocalFilters } = useValues(eventsListLogic(logicProps))
    const { setEventListLocalFilters } = useActions(eventsListLogic(logicProps))
    const { consoleListLocalFilters } = useValues(consoleLogsListLogic(logicProps))
    const { setConsoleListLocalFilters } = useActions(consoleLogsListLogic(logicProps))
    const { windowIds } = useValues(playerMetaLogic(logicProps))

    const tabs = [SessionRecordingPlayerTab.EVENTS, SessionRecordingPlayerTab.CONSOLE]

    return (
        <div className="bg-side p-2 space-y-2">
            <div className="flex justify-between gap-2 flex-wrap">
                <div className="flex flex-1 items-center gap-1">
                    {tabs.map((tabId) => (
                        <LemonButton
                            key={tabId}
                            size="small"
                            icon={TabToIcon[tabId]}
                            status={tab === tabId ? 'primary' : 'primary-alt'}
                            active={tab === tabId}
                            onClick={() => setTab(tabId)}
                            loading={tabsState[tabId] === 'loading'}
                        >
                            {capitalizeFirstLetter(tabId)}
                        </LemonButton>
                    ))}
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                    {tab === SessionRecordingPlayerTab.EVENTS ? (
                        <>
                            <LemonInput
                                key="event-list-search-input"
                                onChange={(query) => setEventListLocalFilters({ query })}
                                placeholder="Search events"
                                type="search"
                                value={eventListLocalFilters.query}
                            />
                            {matching?.length ? (
                                <LemonSwitch
                                    checked={showOnlyMatching}
                                    bordered
                                    label={
                                        <span className="flex items-center gap-2 whitespace-nowrap">
                                            Only show matching events
                                            <Tooltip
                                                title="Display only the events that match the global filter."
                                                className="text-base text-muted-alt mr-2"
                                            >
                                                <IconInfo />
                                            </Tooltip>
                                        </span>
                                    }
                                    onChange={setShowOnlyMatching}
                                />
                            ) : null}
                        </>
                    ) : tab === SessionRecordingPlayerTab.CONSOLE ? (
                        <LemonInput
                            key="console-list-search-input"
                            onChange={(query) => setConsoleListLocalFilters({ query })}
                            placeholder="Search console logs"
                            type="search"
                            value={consoleListLocalFilters.query}
                        />
                    ) : null}
                </div>

                {windowIds.length > 1 ? (
                    <div className="flex items-center gap-2 flex-wrap">
                        <LemonSelect
                            size="small"
                            data-attr="player-window-select"
                            value={windowIdFilter ?? undefined}
                            onChange={(val) => setWindowIdFilter(val || null)}
                            options={[
                                {
                                    value: undefined,
                                    label: 'All windows',
                                    icon: <IconWindow value="A" className="text-muted" />,
                                },
                                ...windowIds.map((windowId, index) => ({
                                    value: windowId,
                                    label: `Window ${index + 1}`,
                                    icon: <IconWindow value={index + 1} className="text-muted" />,
                                })),
                            ]}
                        />
                        <Tooltip
                            title="Each recording window translates to a distinct browser tab or window."
                            className="text-base text-muted-alt mr-2"
                        >
                            <IconInfo />
                        </Tooltip>
                    </div>
                ) : null}
            </div>
        </div>
    )
}
