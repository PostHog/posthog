import { actions, connect, events, kea, key, path, props } from "kea";
import { loaders } from "kea-loaders";
import { router, urlToAction } from "kea-router";
import api from "lib/api";
import { toParams } from "lib/utils";
import { teamLogic } from "scenes/teamLogic";

export interface RelatedFeatureFlagType {

}

export const relatedFeatureFlagsLogic = kea<relatedFeatureFlagsLogic>([
    path(['scenes', 'persons', 'relatedGroupsLogic']),
    connect({ values: [teamLogic, ['currentTeamId']] }),
    actions({
        loadRelatedFeatureFlags: true,
    }),
    props({} as {
        distinctId: string
    }),
    key((props) => `${props.distinctId}`),
    loaders(({ values }) => ({
        relatedFeatureFlags: [
            [] as RelatedFeatureFlagType[],
            {
                loadRelatedFeatureFlags: async () => {
                    const response = await api.get(
                        `api/projects/${values.currentTeamId}/feature_flags/evaluation_reasons?${toParams({
                            distinct_id: props.distinctId
                        })}`
                    )
                    return response.results
                }
            }
        ]
    })),
    // urlToAction(({ actions }) => ({
    //     '/persons/:id': () => {
    //         actions.loadRelatedFeatureFlags
    //     },

    // })),
    events(({ actions }) => ({
        afterMount: actions.loadRelatedFeatureFlags,
    })),
])