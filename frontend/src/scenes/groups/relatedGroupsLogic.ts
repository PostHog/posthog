import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { toParams } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

import { ActorType } from '~/types'

import type { relatedGroupsLogicType } from './relatedGroupsLogicType'

export const relatedGroupsLogic = kea<relatedGroupsLogicType>([
    props(
        {} as {
            groupTypeIndex: number | null
            id: string
            type?: 'person' | 'group'
        }
    ),
    key((props) => `${props.groupTypeIndex ?? 'person'}-${props.id}`),
    path(['scenes', 'groups', 'relatedGroupsLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']] })),
    actions(() => ({
        loadRelatedActors: true,
    })),
    reducers({
        loadStartTime: [
            null as number | null,
            {
                loadRelatedActors: () => performance.now(),
            },
        ],
    }),
    loaders(({ values, props }) => ({
        relatedActors: [
            [] as ActorType[],
            {
                loadRelatedActors: async () => {
                    const url = `api/environments/${values.currentTeamId}/groups/related?${toParams({
                        group_type_index: props.groupTypeIndex,
                        id: props.id,
                        variant: values.variant,
                    })}`
                    return await api.get(url)
                },
                setGroup: () => [],
            },
        ],
    })),
    selectors(({ selectors }) => ({
        relatedPeople: [
            () => [selectors.relatedActors],
            (relatedActors: ActorType[]) => relatedActors.filter((actor) => actor.type === 'person'),
        ],
        variant: [
            (s) => [s.featureFlags],
            (featureFlags) => {
                return featureFlags[FEATURE_FLAGS.OPTIMIZED_RELATED_GROUPS_QUERY]
            },
        ],
    })),
    listeners(({ values, props }) => ({
        loadRelatedActorsSuccess: () => {
            const durationMs =
                values.loadStartTime !== null ? Math.round(performance.now() - values.loadStartTime) : null

            posthog.capture('related actors loaded', {
                duration_ms: durationMs,
                variant: values.variant,
                group_type_index: props.groupTypeIndex,
                id: props.id,
                type: props.type ?? 'group',
                team_id: values.currentTeamId,
                result_count: values.relatedActors.length,
            })
        },
    })),
    events(({ actions }) => ({
        afterMount: actions.loadRelatedActors,
    })),
])
