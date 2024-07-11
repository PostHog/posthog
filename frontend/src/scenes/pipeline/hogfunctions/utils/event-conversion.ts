import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'
import { useMemo } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { HogFunctionType } from '~/types'

export type HogFunctionInvocationGlobals = {
    project: {
        id: number
        name: string
        url: string
    }
    source?: {
        name: string
        url: string
    }
    event: {
        uuid: string
        name: string
        distinct_id: string
        properties: Record<string, any>
        timestamp: string
        url: string
    }
    person?: {
        uuid: string
        name: string
        url: string
        properties: Record<string, any>
    }
    groups?: Record<
        string,
        {
            id: string // the "key" of the group
            type: string
            index: number
            url: string
            properties: Record<string, any>
        }
    >
}

export function useExampleHogGlobals(hogFunction?: Partial<HogFunctionType>): HogFunctionInvocationGlobals {
    const { groupTypes } = useValues(groupsModel)
    const { currentTeam } = useValues(teamLogic)

    return useMemo(() => {
        const globals: HogFunctionInvocationGlobals = {
            event: {
                uuid: uuid(),
                distinct_id: uuid(),
                name: '$pageview',
                properties: {},
                timestamp: dayjs().toISOString(),
                url: `${window.location.origin}/project/${currentTeam?.id}/events/`,
            },
            person: {
                uuid: uuid(),
                name: 'Example person',
                url: `${window.location.origin}/person/${uuid()}`,
                properties: {
                    email: 'example@posthog.com',
                },
            },
            groups: {},
            project: {
                id: currentTeam?.id || 0,
                name: currentTeam?.name || '',
                url: `${window.location.origin}/project/${currentTeam?.id}`,
            },
            source: {
                name: hogFunction?.name ?? 'Unnamed',
                url: window.location.href,
            },
        }

        groupTypes.forEach((groupType) => {
            globals.groups![groupType.group_type] = {
                id: uuid(),
                type: groupType.group_type,
                index: groupType.group_type_index,
                url: `${window.location.origin}/groups/${groupType.group_type_index}/groups/${encodeURIComponent(
                    groupType.group_type_index
                )}`,
                properties: {},
            }
        })

        return globals
    }, [groupTypes])
}
