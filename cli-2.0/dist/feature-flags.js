// Feature flag tool implementations
export const featureFlagTools = {
    'feature-flag-get-all': {
        name: 'feature-flag-get-all',
        handler: async (context, params) => {
            const queryParams = {};
            if (params.search) {
                queryParams.search = params.search;
            }
            if (params.limit) {
                queryParams.limit = params.limit;
            }
            const projectId = await context.stateManager.getProjectId();
            return context.api.request({
                method: 'GET',
                path: `/api/projects/${projectId}/feature_flags/`,
                query: queryParams
            });
        }
    },
    'feature-flag-get-definition': {
        name: 'feature-flag-get-definition',
        handler: async (context, params) => {
            const projectId = await context.stateManager.getProjectId();
            return context.api.request({
                method: 'GET',
                path: `/api/projects/${projectId}/feature_flags/${params.id}/`
            });
        }
    },
    'create-feature-flag': {
        name: 'create-feature-flag',
        handler: async (context, params) => {
            const projectId = await context.stateManager.getProjectId();
            return context.api.request({
                method: 'POST',
                path: `/api/projects/${projectId}/feature_flags/`,
                body: {
                    key: params.key,
                    name: params.name,
                    active: params.active ?? false,
                    rollout_percentage: params.rollout_percentage,
                    filters: params.filters
                }
            });
        }
    }
};
export default featureFlagTools;
