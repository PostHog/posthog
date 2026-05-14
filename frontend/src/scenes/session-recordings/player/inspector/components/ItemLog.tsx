import clsx from 'clsx'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { urls } from 'scenes/urls'

import { ItemTimeDisplay } from '../../../components/ItemTimeDisplay'
import { InspectorListItemLog } from '../playerInspectorLogic'

export interface ItemLogProps {
    item: InspectorListItemLog
    groupCount?: number
    groupedItems?: InspectorListItemLog[]
    sessionId?: string
}

const levelColors: Record<string, string> = {
    trace: 'text-secondary',
    debug: 'text-secondary',
    info: 'text-primary',
    warn: 'text-warning',
    error: 'text-danger',
    fatal: 'text-danger',
}

export function ItemLog({ item, groupCount }: ItemLogProps): JSX.Element {
    const count = groupCount ?? 1
    const showBadge = count > 1

    return (
        <div className="w-full font-light flex items-center" data-attr="item-log">
            <div className="px-2 py-1 text-xs cursor-pointer truncate font-mono flex-1 flex items-center gap-2">
                <span
                    className={clsx('uppercase font-semibold text-xxs', levelColors[item.data.level] || 'text-primary')}
                >
                    {item.data.level}
                </span>
                <span className="truncate">{item.data.body}</span>
            </div>
            {showBadge ? (
                <span
                    className={clsx(
                        'inline-flex items-center justify-center rounded-full min-w-4 h-4 px-0.5 mx-2 shrink-0 text-white text-xxs font-bold',
                        item.highlightColor === 'danger'
                            ? 'bg-fill-error-highlight'
                            : item.highlightColor === 'warning'
                              ? 'bg-fill-warning-highlight'
                              : 'bg-secondary-3000-hover'
                    )}
                >
                    {count}
                </span>
            ) : null}
        </div>
    )
}

export function ItemLogDetail({ item, groupedItems, sessionId }: ItemLogProps): JSX.Element {
    const logsUrl = sessionId
        ? `${urls.logs()}?filterGroup=${encodeURIComponent(
              JSON.stringify({
                  type: 'AND',
                  values: [
                      {
                          type: 'AND',
                          values: [
                              {
                                  key: 'session_id',
                                  value: sessionId,
                                  operator: 'exact',
                                  type: 'log_attribute',
                              },
                          ],
                      },
                  ],
              })
          )}`
        : urls.logs()

    const attributes =
        item.data.attributes && typeof item.data.attributes === 'object'
            ? Object.fromEntries(
                  Object.entries(item.data.attributes).map(([key, value]) => [
                      key,
                      typeof value === 'string' ? value : JSON.stringify(value),
                  ])
              )
            : {}

    return (
        <div className="w-full font-light" data-attr="item-log-detail">
            <div className="px-2 py-1 text-xs border-t">
                <div className="flex justify-between items-center mb-2">
                    <LemonLabel>Log</LemonLabel>
                    <LemonButton type="tertiary" size="xsmall" icon={<IconOpenInNew />} targetBlank to={logsUrl}>
                        View in Logs
                    </LemonButton>
                </div>

                {groupedItems && groupedItems.length > 1 ? (
                    <>
                        <div className="italic mb-1">
                            This log occurred <b>{groupedItems.length}</b> times:
                        </div>
                        <div className="flex flex-col border rounded bg-surface-primary mb-2 max-h-40 overflow-y-auto">
                            {groupedItems.map((entry, i) => (
                                <div
                                    key={entry.key}
                                    className={clsx('flex items-center gap-2 font-mono', i > 0 && 'border-t')}
                                >
                                    <ItemTimeDisplay
                                        timestamp={entry.timestamp}
                                        timeInRecording={entry.timeInRecording}
                                        className="shrink-0 text-secondary !py-0"
                                    />
                                    <span
                                        className={clsx(
                                            'uppercase font-semibold text-xxs',
                                            levelColors[entry.data.level]
                                        )}
                                    >
                                        {entry.data.level}
                                    </span>
                                    <span className="truncate">{entry.data.body}</span>
                                </div>
                            ))}
                        </div>
                    </>
                ) : null}

                <CodeSnippet language={Language.Text} wrap thing="log message">
                    {item.data.body}
                </CodeSnippet>

                {item.data.instrumentation_scope ? (
                    <>
                        <LemonDivider dashed />
                        <LemonLabel>Service</LemonLabel>
                        <div className="font-mono text-xs">{item.data.instrumentation_scope}</div>
                    </>
                ) : null}

                {Object.keys(attributes).length > 0 ? (
                    <>
                        <LemonDivider dashed />
                        <LemonLabel>Attributes</LemonLabel>
                        <SimpleKeyValueList item={attributes} />
                    </>
                ) : null}
            </div>
        </div>
    )
}
