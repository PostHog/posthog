import { router } from 'kea-router'

import { IconWarning } from '@posthog/icons'

import { ErrorTrackingException, ErrorTrackingRuntime } from 'lib/components/Errors/types'
import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { Dayjs, dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

import { ItemCategory, ItemLoader, ItemRenderer, TimelineItem } from '..'
import { StandardizedPreview } from './base'
import { LazyEventDetailsRenderer } from './eventDetails'

export interface ExceptionItem extends TimelineItem {
    payload: {
        runtime: ErrorTrackingRuntime
        type: string
        message: string
        issue_id: string
        fingerprint: string
    }
}

/**
 * Static loader that holds a single pre-built exception item in memory.
 * Used when there is no session ID but we still want to show the current
 * exception on the timeline alongside exception steps.
 */
export class StaticExceptionLoader implements ItemLoader<ExceptionItem> {
    private readonly item: ExceptionItem

    constructor(uuid: string, timestamp: Dayjs, properties?: Record<string, any>) {
        const runtime: ErrorTrackingRuntime = getRuntimeFromLib(properties?.$lib)
        const exceptionList: ErrorTrackingException[] | undefined = properties?.$exception_list
        this.item = {
            id: uuid,
            category: ItemCategory.ERROR_TRACKING,
            timestamp: dayjs.utc(timestamp),
            payload: {
                runtime,
                type: exceptionList?.[0]?.type ?? 'Exception',
                message: exceptionList?.[0]?.value ?? '',
                fingerprint: properties?.$exception_fingerprint ?? '',
                issue_id: properties?.$exception_issue_id ?? '',
            },
        }
    }

    async loadBefore(cursor: Dayjs): Promise<{ items: ExceptionItem[]; hasMoreBefore: boolean }> {
        return {
            items: this.item.timestamp.isBefore(cursor) ? [this.item] : [],
            hasMoreBefore: false,
        }
    }

    async loadAfter(cursor: Dayjs): Promise<{ items: ExceptionItem[]; hasMoreAfter: boolean }> {
        return {
            items: this.item.timestamp.isAfter(cursor) ? [this.item] : [],
            hasMoreAfter: false,
        }
    }
}

export const exceptionRenderer: ItemRenderer<ExceptionItem> = {
    sourceIcon: ({ item }) => <RuntimeIcon runtime={item.payload.runtime} />,
    categoryIcon: <IconWarning />,
    render: ({ item }): JSX.Element => {
        const errorType = item.payload.type || 'Exception'
        const errorMessage = item.payload.message || 'Exception captured'

        return <StandardizedPreview primaryText={errorType} secondaryText={errorMessage} secondaryMuted />
    },
    renderExpanded: LazyEventDetailsRenderer,
    getMenuItems: ({ item }) =>
        item.payload.issue_id
            ? [
                  {
                      key: 'open-exception-issue',
                      label: 'Open exception issue',
                      onClick: () =>
                          router.actions.push(
                              urls.errorTrackingIssue(item.payload.issue_id, {
                                  fingerprint: item.payload.fingerprint,
                                  timestamp: item.timestamp.toISOString(),
                              })
                          ),
                  },
              ]
            : [],
}
