import { kea, key, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { combineUrl } from 'kea-router'

import { colonDelimitedDuration, reverseColonDelimitedDuration } from 'lib/utils'
import { urls } from 'scenes/urls'

import type { playerShareLogicType } from './playerShareLogicType'

export interface FormWithTime {
    includeTime: boolean
    time: string | null
}

function makePrivateLinkQueryParams(formWithTime: FormWithTime): Record<string, string | undefined> {
    return {
        t: formWithTime.includeTime ? `${reverseColonDelimitedDuration(formWithTime.time) || 0}` : undefined,
    }
}

export function makePrivateLink(id: string, formWithTime: FormWithTime): string {
    return combineUrl(
        urls.absolute(urls.currentProject(urls.replaySingle(id))),
        makePrivateLinkQueryParams(formWithTime)
    ).url
}

export type PlayerShareLogicProps = {
    seconds: number | null
    id: string
    shareType?: 'private' | 'public' | 'linear'
}

export const playerShareLogic = kea<playerShareLogicType>([
    path(() => ['scenes', 'session-recordings', 'player', 'playerShareLogic']),
    props({} as PlayerShareLogicProps),
    key((props: PlayerShareLogicProps) => `${props.id}-${props.seconds}`),

    forms(({ props }) => ({
        privateLinkForm: {
            defaults: { includeTime: true, time: colonDelimitedDuration(props.seconds, null) } as FormWithTime,
            errors: ({ time, includeTime }) => ({
                time:
                    time && includeTime && reverseColonDelimitedDuration(time || undefined) === null
                        ? 'Set a valid time like 02:30 (minutes:seconds)'
                        : undefined,
            }),
            options: {
                // whether we show errors after touch (true) or submit (false)
                showErrorsOnTouch: true,

                // show errors even without submitting first
                alwaysShowErrors: true,
            },
        },
        linearLinkForm: {
            defaults: {
                includeTime: true,
                time: colonDelimitedDuration(props.seconds, null),
                issueTitle: '',
                issueDescription: '',
            } as FormWithTime & {
                issueTitle: string
                issueDescription: string
            },
            errors: ({ time, includeTime }) => ({
                time:
                    time && includeTime && reverseColonDelimitedDuration(time || undefined) === null
                        ? 'Set a valid time like 02:30 (minutes:seconds)'
                        : undefined,
            }),
            options: {
                // whether we show errors after touch (true) or submit (false)
                showErrorsOnTouch: true,

                // show errors even without submitting first
                alwaysShowErrors: true,
            },
        },
    })),

    selectors(({ props }) => ({
        privateLinkUrlQueryParams: [
            (s) => [s.privateLinkForm],
            (privateLinkForm) => {
                return makePrivateLinkQueryParams(privateLinkForm)
            },
        ],
        privateLinkUrl: [
            (s) => [s.privateLinkForm],
            (privateLinkForm) => {
                return makePrivateLink(props.id, privateLinkForm)
            },
        ],
        linearQueryParams: [
            (s) => [s.linearLinkForm],
            (linearLinkForm) => {
                return {
                    title: linearLinkForm.issueTitle,
                    description:
                        linearLinkForm.issueDescription +
                        `\n\nPostHog recording: ${makePrivateLink(props.id, linearLinkForm)}`,
                }
            },
        ],
        linearUrl: [
            (s) => [s.linearQueryParams],
            (linearQueryParams) => {
                return combineUrl('https://linear.app/new', linearQueryParams).url
            },
        ],
    })),
])
